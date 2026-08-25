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
from datetime import datetime, timezone
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
    buildinfo as buildinfo_mod,
    config,
    consent_write,
    fit,
    ids,
    insight,
    outreach_write,
    policy as policy_mod,
    profile as prof,
    profile_write,
    resume_write,
    scheduler as sched_mod,
    search as search_mod,
    sync as sync_mod,
)
from jobcore import config as jobcore_config

from uplers_server.client import UplersClient, UplersError
from uplers_server.models import (
    AlertList,
    AlertResult,
    AlertSpec,
    BriefSection,
    CompanyIntel,
    ConfigReport,
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
    ServerInfo,
    SkillGapResult,
    SkillGapRow,
    SyncResult,
    TrackedJob,
    TrackedList,
    TrackResult,
)
from uplers_server import (
    agent_surface,
    assessment_flags,
    auth as auth_mod,
    endpoints,
    outreach as outreach_mod,
    preference as preference_mod,
    saved_filter,
    session as session_mod,
    skus,
    talent_shape,
)
from uplers_server.search import notice_days
from uplers_server.session import SessionStore
from uplers_server.shaping import to_detail, to_opportunity
from uplers_server.store import Store
from uplers_server.talent import AuthRequired, TalentClient, TalentError
from uplers_server.talent_models import (
    AuthStatus,
    FieldChange,
    FieldDiff,
    FieldReport,
    InterviewList,
    MyAssessments,
    LoginResult,
    PipelineResult,
    ProfileComparison,
    ProfileSyncResult,
    ProfileWriteResult,
    SnapshotEntry,
    SnapshotList,
    TalentFeed,
    TalentProfileResult,
    WritePreview,
    WriteResult,
)

INSTRUCTIONS = (
    "Reader, tracker and application client for the Uplers talent board. Its unique "
    "value is the END CLIENT COMPANY NAME on Uplers-native requisitions, which job "
    "boards hide. Scoring is jobcore's, shared with the Naukri server, so a fit score "
    "means the same thing on both.\n\n"
    "TWO TIERS. The PUBLIC tier needs no account: call uplers_sync_index() first (it "
    "builds the local index), then everything is served from the local cache and costs "
    "no network - uplers_daily_brief() is the usual entry point and "
    "uplers_rank_opportunities() the main search. The AUTHENTICATED tier needs a "
    "signed-in session (uplers_login, then uplers_auth_status to confirm) and reads HIS "
    "account: uplers_my_feed is his personalised feed, uplers_my_pipeline his real "
    "applications with Uplers' own authoritative status, uplers_my_profile the profile "
    "recruiters actually see.\n\n"
    "SESSIONS ARE SHORT-LIVED - expect to re-run uplers_login roughly daily. An "
    "authenticated tool that reports an expired session means exactly that; it never "
    "returns an empty list instead.\n\n"
    "WRITES. uplers_apply expresses interest, which on Uplers IS applying and CANNOT BE "
    "UNDONE - there is no withdraw anywhere in their product. uplers_dismiss is "
    "reversible. Both perform nothing unless confirm=True and otherwise return a "
    "preview. uplers_track() remains the local record of what the human did elsewhere."
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
        % policy_mod.display_path(str(store.path))
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
    include_aggregated: bool | None = None,
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
        include_aggregated: opt in to the ~39k scraped postings. Unset takes
            servers.uplers.include_aggregated, whose default is off, because
            they duplicate JobSpy/Naukri coverage and drown the signal.
        sort: newest | oldest | pay_desc | pay_asc | least_competition.
        limit: max rows returned; `matched` reports the true total.
    """
    include_aggregated = _aggregated(include_aggregated)
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
    include_aggregated: bool | None = None,
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
        include_aggregated: fold in the ~39k scraped postings. Unset takes
            servers.uplers.include_aggregated, whose default is off; most of
            them carry no pay data, which skews every figure.
    """
    include_aggregated = _aggregated(include_aggregated)
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


def _load_pairs(store: Store, *, include_aggregated: bool | None = None, bound=None):
    """(raw, Opportunity) for every cached record. Raises on an empty index.

    ``include_aggregated=None`` takes ``servers.uplers.include_aggregated``,
    whose default is today's ``False``.
    """
    include_aggregated = _aggregated(include_aggregated, bound)
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


def _load_opportunities(store: Store, *, include_aggregated: bool | None = None, bound=None):
    return [
        opp for _, opp in _load_pairs(
            store, include_aggregated=include_aggregated, bound=bound)
    ]


def _aggregated(value: bool | None, bound=None) -> bool:
    """Resolve an ``include_aggregated`` argument against the config default."""
    if value is not None:
        return bool(value)
    return bool(policy_mod.resolve(bound).setting("include_aggregated", default=False))


def _bind():
    """Read the shared policy ONCE for this tool call.

    Every scoring tool starts here. A config change that lands mid-call must
    not be seen by that call: half a ranking scored under old weights and half
    under new is worse than either.
    """
    return policy_mod.bind()


def _candidate_patch(local) -> dict:
    """The shared ``candidate`` block this local profile implies.

    Only fields that actually hold a value are included: ``None`` at a leaf
    means "revert to the shipped default" in the config document, which is not
    what "my profile does not say" means.

    Pay is written in USD/year and ONLY in USD/year. The lakhs band beside it
    belongs to the Naukri server, and one shared scalar would score every job
    on this board +5 and every job on that one 0 - both looking exactly like
    "no salary data". Nothing is converted: an exchange rate is not a fact
    about him, and a score must not depend on the day.
    """
    out: dict = {}
    for key, attr in policy_mod.FIELD_MAP:
        value = getattr(local, attr, None)
        if value in (None, [], ()):
            continue
        out[key.split(".", 1)[1]] = (
            list(value) if isinstance(value, (list, tuple)) else value
        )
    if local.location:
        out["locations"] = [local.location]
    band: dict = {}
    if local.min_pay_usd_year is not None:
        band["floor"] = local.min_pay_usd_year
    expected = policy_mod.expected_pay(local)
    if expected is not None:
        band["expected"] = expected
    if band:
        out["pay"] = {policy_mod.PAY_UNIT: band}
    return out


def _profile_summary(profile, bound=None) -> ProfileSummary:
    """Attached to every scored result, so a score is never orphaned from
    the profile it was computed against - nor from the policy that scored it.

    TWO fingerprints, because they answer two different questions and one name
    over both is what made "is this score still current" unanswerable.

    `policy_hash` covers the scoring arithmetic AND the candidate block: the
    identity of the whole setup, and what an approval gate compares.

    `scoring_hash` covers the arithmetic alone - weights, bonuses, caps,
    verdict bands. THIS is the comparability field. It is the value stamped on
    a scored result and reported by uplers_config(), and it is what the Naukri
    server stamps too, so an equal one there means the two numbers were
    produced by the same sums. The candidate half is deliberately outside it:
    a result can only vouch for the arithmetic.

    Neither is truncated. Both are already 12 characters.
    """
    bound = policy_mod.resolve(bound)
    return ProfileSummary(
        years_experience=profile.years_experience,
        location=profile.location,
        skills=len(profile.skills),
        notice_period_days=profile.notice_period_days,
        min_pay_usd_year=profile.min_pay_usd_year,
        expected_pay_usd_year=policy_mod.expected_pay(profile),
        policy_hash=bound.policy_hash,
        scoring_hash=bound.scoring_hash,
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
    if policy_mod.expected_pay(profile) is None:
        notes.append(
            "Neither expected_pay_usd_year nor min_pay_usd_year is set, so there is "
            "nothing to score a pay band against and the +5 salary bonus never applies."
        )
    return notes


def _require_profile(bound=None):
    """(profile, notes). Seeds from the resume on first use, loudly.

    The profile returned is the LOCAL `data/profile.json` with every field the
    shared `candidate` block actually configures applied on top. Precedence is
    stated rather than discovered: a field present in the config file wins,
    everything else stays local. With no config file nothing is configured, so
    this is the local profile unchanged, field for field.
    """
    bound = policy_mod.resolve(bound)
    try:
        local, seeded = prof.load_or_seed()
    except prof.ProfileError as exc:
        raise UplersError(str(exc)) from exc
    profile, where = policy_mod.effective_profile(local, bound)
    if not profile.is_usable():
        raise UplersError(
            "The stored profile has no skills and no years_experience, so every fit score "
            "would be meaningless. Set it with uplers_set_profile(skills=[...], "
            "years_experience=...)."
        )
    notes = _profile_notes(profile, seeded=seeded)
    shared = sorted(field for field, source in where.items() if source == "config")
    if shared:
        notes.append(
            "%d profile field(s) come from the shared config, not from "
            "data/profile.json: %s. uplers_config() shows the file and its "
            "provenance." % (len(shared), ", ".join(shared))
        )
    notes.extend(bound.notes())
    return (profile, notes)


def _ensure_scheduler(bound=None) -> None:
    """Start background freshness on first use, inside the running event loop.

    Lazy rather than at import for two reasons: importing this module in a
    test must not spawn a network task, and a server nobody calls should not
    sync. Both MCP clients that register `uplers` run their own copy, so the
    task itself is lease-guarded - see scheduler.py.
    """
    # Bind for ourselves when nobody handed one down: a tool that neither
    # scores nor reads a setting must still honour auto_sync.enabled, and the
    # alternative is seven call sites that each remember to.
    if bound is None:
        bound = _bind()
    if not sched_mod.enabled(bound):
        return
    try:
        scheduler = sched_mod.get_scheduler(bound)
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
    bound = _bind()
    _ensure_scheduler(bound)
    try:
        local, seeded = prof.load_or_seed()
    except prof.ProfileError as exc:
        raise UplersError(str(exc)) from exc
    effective, where = policy_mod.effective_profile(local, bound)
    notes = _profile_notes(effective, seeded=seeded)
    shared = sorted(field for field, source in where.items() if source == "config")
    if shared:
        notes.append(
            "Scoring uses the SHARED config for: %s. The rest comes from %s. "
            "The profile shown is what actually scores." % (
                ", ".join(shared),
                policy_mod.display_path(str(prof.profile_path())),
            )
        )
    notes.extend(bound.notes())
    return ProfileResult(
        profile=effective,
        path=policy_mod.display_path(str(prof.profile_path())),
        seeded_from_resume=seeded,
        config_source=policy_mod.display_path(bound.loaded.source),
        field_source=where,
        notes=notes,
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
    expected_pay_usd_year: int | None = None,
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
        min_pay_usd_year: WALK-AWAY floor in Uplers' USD/year normalisation.
            Roles below it are flagged, never hidden.
        expected_pay_usd_year: the figure the +5 salary bonus is scored
            against - a separate decision from the floor. Unset means "use the
            floor", which is what this server did when one number was doing
            both jobs. Always USD/year: a lakhs figure here would read as
            dollars and score every role as a windfall.
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
    if expected_pay_usd_year is not None:
        profile.expected_pay_usd_year = expected_pay_usd_year
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
    return ProfileResult(
        profile=profile, path=policy_mod.display_path(str(path)), notes=notes
    )


# ---------------------------------------------------------------- tool 8 ---


@mcp.tool()
async def uplers_assess_fit(
    hr_number: str, refresh: bool = False, explain: bool = False
) -> FitAssessment:
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
        explain: show the arithmetic, not just the number - the two weighted
            components, every bonus and whether the cap bit, the verdict band
            the score fell in, and the scoring_hash. This is the one tool
            where it is worth it: you are already reading one role in full,
            and this is the surface that answers "why 78 and not 85". Off by
            default because it is roughly another row's worth of tokens.
    """
    bound = _bind()
    _ensure_scheduler(bound)
    normalised = _validate_hr(hr_number)
    profile, notes = _require_profile(bound)
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
        assessment = fit.assess(opp, profile, bound, explain=explain)
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
            explain=assessment.get("explain"),
            scored_against=_profile_summary(profile, bound),
            notes=notes,
        )


# ---------------------------------------------------------------- tool 9 ---


@mcp.tool()
async def uplers_rank_opportunities(
    limit: int = 10,
    min_score: int | None = None,
    exclude_blocked: bool | None = None,
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
    include_aggregated: bool | None = None,
    saved_only: bool = False,
    explain: bool = False,
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
            Unset takes servers.uplers.exclude_blocked.rank, default True.
        skill / title / company / mode_of_work / remote_only / currency /
            min_pay_usd_year / joining_period / min_notice_days / max_yoe:
            narrow the population before scoring, same meanings as
            uplers_search_opportunities.
        include_aggregated: fold in the ~39k scraped postings. Unset takes
            servers.uplers.include_aggregated, default off.
        saved_only: rank just your shortlist.
        explain: attach the arithmetic to EVERY row returned. The cost scales
            with `limit`, which is why it is off here and why the usual move
            is to rank first and then explain the one row that surprised you
            with uplers_assess_fit(explain=True). Reach for it here only when
            you are comparing how two roles got their scores.
    """
    bound = _bind()
    _ensure_scheduler(bound)
    profile, notes = _require_profile(bound)
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
        include_aggregated = _aggregated(include_aggregated, bound)
        exclude_blocked = (
            bound.setting("exclude_blocked", "rank", default=True)
            if exclude_blocked is None else exclude_blocked
        )
        population = _load_opportunities(
            store, include_aggregated=include_aggregated, bound=bound)
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
        ranked, blocked, unscorable = fit.rank(
            population, profile, exclude_blocked=exclude_blocked, bound=bound,
            explain=explain)
        if unscorable:
            notes.append(
                "%d cached record(s) carried neither skills nor an experience band "
                "and were left OUT of the ranking rather than scored at a neutral "
                "50: %s. Re-run uplers_sync_index() if they should be complete."
                % (len(unscorable), ", ".join(unscorable[:5]))
            )
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
            scored_against=_profile_summary(profile, bound),
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
async def uplers_list_saved(
    score: bool = True, limit: int = 25, explain: bool = False
) -> SavedList:
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
        explain: show how each of those scores was reached. Useful for exactly
            one question here - "why is this one worth less than when I saved
            it" - and answered by reading the bonus table and the band. Does
            nothing when score=False, since there is then no score to explain.
    """
    bound = _bind()
    _ensure_scheduler(bound)
    with _open_store() as store:
        rows = store.list_saved()
        notes = []
        profile = None
        if score and rows:
            try:
                profile, notes = _require_profile(bound)
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
                    try:
                        assessment = fit.assess(opp, profile, bound, explain=explain)
                    except fit.UnscorableOpportunity as exc:
                        notes.append("%s not scored: %s" % (row["hr_number"], exc))
                    else:
                        entry.score = assessment["overall_score"]
                        entry.explain = assessment.get("explain")
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
        due = brief_mod.follow_up_due(store, bound=_bind())
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
    bound = _bind()
    _ensure_scheduler(bound)
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
            population = _load_opportunities(store, bound=bound)
            profile = None
            if min_score is not None or exclude_blocked:
                profile, profile_notes = _require_profile(bound)
                notes.extend(profile_notes)
            matches = len(alerts_mod.evaluate(population, criteria, profile, bound=bound))
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
async def uplers_list_alerts(
    evaluate: bool = False, rows: int = 3, explain: bool = False
) -> AlertList:
    """Your saved alerts, optionally run right now.

    Use it: to see what is being watched, and to check an alert is not
    silently matching nothing.

    Args:
        evaluate: run each alert against the current index and report how many
            requisitions match and how many are new since it last reported.
            Local only, no network.
        rows: sample rows per alert when evaluating.
        explain: attach the arithmetic to each sampled row. The question it
            answers here is about the ALERT rather than the role - a min_score
            gate that lets nothing through, or lets everything through, is
            usually a bonus or a band behaving differently from how you read
            it. Needs evaluate=True; an unevaluated listing scores nothing.
    """
    bound = _bind()
    _ensure_scheduler(bound)
    with _open_store() as store:
        stored = store.list_alerts()
        notes = []
        profile = None
        population = []
        if evaluate and stored:
            try:
                population = _load_opportunities(store, bound=bound)
            except UplersError as exc:
                notes.append("Could not evaluate: %s" % exc)
                evaluate = False
            if evaluate and any(
                "min_score" in alert["criteria"] or alert["criteria"].get("exclude_blocked")
                for alert in stored
            ):
                try:
                    profile, profile_notes = _require_profile(bound)
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
                    matches = alerts_mod.evaluate(
                        population, alert["criteria"], profile, bound=bound,
                        explain=explain)
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
    limit: int = 5, since: str | None = None, peek: bool = False,
    explain: bool = False,
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
        explain: attach the arithmetic to the new-requisition rows and the
            alert hits. Against the grain of this tool, which exists to be
            cheap enough to call every morning - it can multiply the brief
            across two sections at once. Leave it off for the daily read and
            drill into whatever looked wrong with uplers_assess_fit().
    """
    bound = _bind()
    _ensure_scheduler(bound)
    profile, notes = _require_profile(bound)
    with _open_store() as store:
        population = _load_opportunities(store, bound=bound)
        data = brief_mod.build(
            store, profile, population, limit=limit, since=since, peek=peek,
            bound=bound, explain=explain,
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
            scored_against=_profile_summary(profile, bound),
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
    bound = _bind()
    _ensure_scheduler(bound)
    profile, notes = _require_profile(bound)
    with _open_store() as store:
        population = _load_opportunities(store, bound=bound)
        data = insight.skill_gap(
            population, profile, top=top, min_roles=min_roles, bound=bound)
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
            scored_against=_profile_summary(profile, bound),
            notes=notes,
        )


# --------------------------------------------------------------- tool 21 ---


@mcp.tool()
async def uplers_company_intel(
    name: str, limit: int = 5, explain: bool = False
) -> CompanyIntel:
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
        explain: show the arithmetic on `best_fit` and every row beside it.
            Worth it on a client posting several roles at once, where the
            useful question is why their openings score so differently from
            each other. The aggregate posture above the rows is counted, not
            scored, so it is unaffected.
    """
    bound = _bind()
    _ensure_scheduler(bound)
    profile = None
    notes: list[str] = []
    try:
        profile, notes = _require_profile(bound)
    except UplersError as exc:
        notes = ["Fit scores omitted: %s" % exc]
    with _open_store() as store:
        pairs = _load_pairs(store, bound=bound)
        data = insight.company_intel(
            pairs, name, profile, bound=bound, explain=explain)
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
    bound = _bind()
    _ensure_scheduler(bound)
    scheduler = sched_mod.get_scheduler(bound)
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


# ------------------------------------------------------------ tool 16 ---


@mcp.tool()
async def uplers_config(write_candidate: bool = False,
                        allow_score_raising: bool = False) -> ConfigReport:
    """Show the shared jobhunt.json this server scores under - and what it refused.

    Every number that decides a score, a blocker or an order lives in that one
    file: the skill/experience split, the bonus table, the verdict bands, the
    stack preference that ranks Python-leaning roles below Node ones, and this
    server's own `servers.uplers` settings. Nothing here is a constant in the
    code any more, and this tool is how you see what is actually in force.

    TWO fingerprints come back, and they answer two different questions.
    `scoring_hash` answers "are these two scores comparable" - it covers the
    arithmetic alone and is the value stamped on every scored result, so
    compare a stored score's stamp against THIS one. `policy_hash` answers
    "is this the same configuration" - it covers the arithmetic AND the
    candidate block, so it moves when your own details change even though no
    sum did.

    `refused` is the important field. Some keys are NOT loadable from the file
    at any tier - the autonomous-apply switches on the Naukri server, chiefly.
    A file that sets one is refused loudly and the Python value is used; it is
    never silently ignored. If something you edited is not taking effect, it
    is in `refused` or `unknown_keys`.

    Use it: when a score looks wrong, before and after editing the file, and
    to find out where the file even is - `searched` lists every path tried
    when none was found.

    Args:
        write_candidate: copy your LOCAL data/profile.json into the shared
            `candidate` block, so every server scores against one description
            of you instead of four. Goes through jobcore's audited write path,
            which means it takes the lock, records the change, and REFUSES
            anything the tier rules do not allow - the refusals come back
            verbatim rather than being worked around. It writes `candidate`
            and nothing else: not `scoring`, not another server's settings,
            and never your real Uplers profile, which lives on Uplers and is
            reached only by uplers_sync_profile_from_uplers().
        allow_score_raising: adding skills or raising years_experience raises
            every score, so those writes need this flag as well. Removing and
            lowering never do.
    """
    bound = _bind()
    _ensure_scheduler(bound)
    ld = bound.loaded
    notes = list(bound.notes())
    write: dict = {}

    if write_candidate:
        try:
            local, _ = prof.load_or_seed()
        except prof.ProfileError as exc:
            raise UplersError(str(exc)) from exc
        patch = {"candidate": _candidate_patch(local)}
        write = jobcore_config.apply_patch(
            patch,
            start=Path(prof.__file__),
            base_revision=ld.revision if ld.source else None,
            actor="uplers_config",
            allowed_sections=("candidate",),
            confirm_widen=allow_score_raising,
        )
        if write.get("status") == "ok":
            policy_mod.invalidate()
            bound = _bind()
            ld = bound.loaded
            notes.append(
                "candidate written to %s (revision %s). Every server that reads this "
                "file now scores against it; data/profile.json stays as the local "
                "fallback for anything the file does not set."
                % (policy_mod.display_path(ld.source), write.get("revision"))
            )
        elif write.get("status") == "no_config_file":
            notes.append(
                "Nothing was written: there is no jobhunt.json yet. Create one at any "
                "of the searched paths (a `config/jobhunt.json` beside a `.jobhunt-root` "
                "marker file is the intended home), or set JOBHUNT_CONFIG in the MCP "
                "host's env block - a stdio child inherits nothing else."
            )
        else:
            notes.append(
                "Nothing was written: %s. The refusals are exact and are not worked "
                "around here." % write.get("status")
            )

    try:
        local_profile, _ = prof.load_or_seed()
        field_source = policy_mod.effective_profile(local_profile, bound)[1]
    except prof.ProfileError:
        field_source = {}

    # Every path leaves through display_path. `status` comes from jobcore's own
    # `status_for`, which composes the sentence and substitutes every known path
    # inside it in one step - this server used to rebuild that sentence by hand,
    # which worked but was a second place for the wording to drift from the
    # library that owns it.
    source = policy_mod.display_path(ld.source)
    searched = [policy_mod.display_path(path) for path in ld.searched]
    # jobcore's own substitution runs inside `status_for` and searches for the
    # SINGLE-separator spelling only, so it renders the `{path}` half of
    # "cannot read {path}: {exc}" and leaves the `{exc}` half - the same path,
    # spelled the way repr() spells it - untouched. That cannot be fixed from
    # here without editing jobcore, so the result takes a second pass through
    # this server's own binding, which knows both spellings. The pass is a
    # no-op on anything jobcore already replaced.
    status = policy_mod.relativise_known_paths(
        ld.status_for(policy_mod.display_path), ld
    )
    # jobcore hands `write` back verbatim and it carries paths in three places:
    # `path` on success, `ledger_error`, and `detail` on a lock conflict. The
    # last two name files DERIVED from the config's directory, which is why the
    # substitution has to key on `known_paths` (parents included) rather than on
    # source+searched.
    write = policy_mod.relativise_mapping(write, ld)

    return ConfigReport(
        source=source,
        status=status,
        revision=ld.revision,
        policy_rev=ld.policy_rev,
        policy_hash=ld.policy_hash,
        scoring_hash=ld.scoring_hash,
        candidate=ld.policy.candidate.to_dict(),
        scoring=ld.policy.scoring.to_dict(),
        server=bound.settings,
        field_source=field_source,
        provenance={
            key: source for key, source in ld.provenance.items() if source == "file"
        },
        refused=list(ld.tier_c_refusals),
        unknown_keys=list(ld.unknown_keys),
        searched=searched if ld.source is None else [],
        write=write,
        notes=notes,
    )


# --- what this server says about itself -----------------------------------
#
# EVERY VALUE BELOW IS A HAND-MAINTAINED DECLARATION, and that is a trade made
# on purpose rather than an oversight. `uplers_server_info` must reach for
# NOTHING - no `list_tools()`, no file read, no git, no network, no database -
# because it is the tool you call when the server's behaviour is ALREADY UNDER
# SUSPICION, and an introspection tool that runs the machinery under suspicion
# cannot answer for it. tests/test_tools.py files it under
# INTROSPECTION_TOOL_NAMES for exactly that property: "its blast radius is zero
# and it is the one tool that must stay that way".
#
# The cost of that choice is that a declaration can go stale, so the check
# MOVES TO THE SUITE, where it costs nothing at runtime.
# tests/test_server_info.py asserts that every tool name declared below is a
# REGISTERED tool and that every census count matches the pinned set in
# tests/test_tools.py. A new write landing without a line here is precisely the
# staleness this tool exists to catch, and that guard is planted-control tested
# rather than assumed.

#: Pinned by TestTheDeclaredSurfaceMatchesReality, against `list_tools()` for
#: the total and against the `# THE AUTHENTICATED TIER` banner in this file for
#: the split. That banner is the only definition of the split there is: it is a
#: physical line in this module, and which side of it a tool is defined on IS
#: whether that tool needs an account.
TOOL_COUNTS = {"total": 62, "public": 24, "authenticated": 38}

#: Can change something ON UPLERS, acting on a requisition.
REQUISITION_WRITE_TOOLS = ("uplers_apply", "uplers_dismiss")

#: Can change something ON UPLERS, acting on HIM. A different kind of act with
#: a different worst case: an apply is irreversible but bounded to one job;
#: these replace a whole field on the profile recruiters read.
PROFILE_WRITE_TOOLS = (
    "uplers_update_profile",
    "uplers_restore_profile",
    "uplers_replace_resume",
    "uplers_restore_resume",
)

#: Can change what UPLERS' OWN PAID AGENT does next - the write half of the
#: four switches `uplers_agent_settings` reads. A third kind of act again: none
#: of these touches a requisition or the profile a recruiter reads, and all
#: five are REVERSIBLE, which is why they were built when the rest of the
#: namespace was not. Two are a route pair Uplers ships (block/unblock); three
#: overwrite a settings record that a GET on the same data serves back, so the
#: prior value is read before the write and reported after it.
#:
#: What is NOT here is the point of the grouping: nothing in this set applies
#: to anything, sends a message to a person, or reveals a contact. See
#: OUT_OF_SCOPE_BY_DESIGN.
AGENT_CONFIG_WRITE_TOOLS = (
    "uplers_set_followup",
    "uplers_set_auto_reply",
    "uplers_set_template",
    "uplers_block_company",
    "uplers_unblock_company",
)

#: Added 2026-08-25. THE GROUP THAT EXISTS BECAUSE THE ONE ABOVE HAS A STATED
#: PROPERTY: every tool in AGENT_CONFIG_WRITE_TOOLS can be put back, and that
#: sentence is the entire reason those five were built while the rest of the
#: namespace was not. Neither of these two is a reversible settings switch, so
#: filing them there would not be a tidier census - it would silently retire
#: the only claim that census makes.
#:
#: They are also not each other's kind, which is why the group's note names
#: both rather than generalising:
#:
#:   * uplers_revoke_email_scan IS reversible on Uplers (POST the same URL
#:     re-grants) but withdraws a standing PERMISSION rather than flipping a
#:     setting, and re-granting starts a FRESH scan rather than resuming. It
#:     was refused for a year on WHOSE CALL IT IS, never on safety; the tool
#:     exists so he can make the call and still performs nothing unconfirmed.
#:   * uplers_submit_interview_feedback is genuinely ONE-WAY - no edit route,
#:     no delete route, complete negative search - and is the only tool in this
#:     server that reaches a one-way `talent/outreach/*` route at all.
#:
#: Neither applies to anything, sends a message to a person, or reveals a
#: contact. That line has not moved.
CONSENT_AND_ONE_WAY_WRITE_TOOLS = (
    "uplers_revoke_email_scan",
    "uplers_submit_interview_feedback",
)

#: The only tool that can write a file OTHER servers read.
SHARED_CONFIG_WRITE_TOOLS = ("uplers_config",)

#: `LOCAL_WRITE_TOOL_NAMES` in tests/test_tools.py. The label overstates two of
#: the three, and WRITE_CENSUS says so rather than letting the grouping imply
#: otherwise.
LOCAL_STATE_ONLY_TOOLS = (
    "uplers_sync_profile_from_uplers",
    "uplers_list_profile_snapshots",
    "uplers_list_resume_snapshots",
)

#: No undo anywhere in Uplers' product. The existing `irreversible_tools` field
#: is this tuple and stays exactly this tuple.
IRREVERSIBLE_TOOLS = ("uplers_apply",)

#: A one-way door on UPLERS' side that this server makes recoverable, and only
#: locally. Deliberately NOT merged into IRREVERSIBLE_TOOLS: flattening the two
#: would either promise a rollback for `uplers_apply` that does not exist, or
#: deny the one for `uplers_replace_resume` that does.
ONE_WAY_DOOR_TOOLS = ("uplers_replace_resume",)

CAPABILITIES = [
    "%d tools. %d need no account at all; %d read or write his signed-in "
    "Uplers account."
    % (TOOL_COUNTS["total"], TOOL_COUNTS["public"], TOOL_COUNTS["authenticated"]),
    "THE END CLIENT COMPANY NAME on Uplers-native requisitions - the field the "
    "job boards hide, where LinkedIn shows the same requisition as 'Uplers' and "
    "stops. This is the reason the server exists.",
    "Board index and search, served OFFLINE: uplers_sync_index builds a local "
    "sqlite index from the public sitemap plus one public JSON route, and every "
    "board read after it costs no network.",
    "Fit scoring against his profile using jobcore's scoring - the SAME scoring "
    "the Naukri server uses, so a fit score means the same thing on both. "
    "config.scoring_hash is stamped on every scored result.",
    "A local shortlist, application tracker, alert set and scheduler. None of "
    "it is ever sent to Uplers; uplers_track is the record of what the human "
    "did elsewhere.",
    "His account once signed in: personalised feed, real pipeline carrying "
    "Uplers' OWN authoritative status, the profile recruiters actually see, "
    "interviews, assessments, and the platform's saved-jobs view.",
    "READ-THROUGH of the paid outreach agent HE ALREADY OWNS - what it ran, "
    "what it found, and how it is configured. This server does not run an "
    "agent and will not build one; see out_of_scope_by_design.",
    "CONFIGURING that agent: the five REVERSIBLE switches - follow-up per "
    "channel, auto-reply, message templates, and the block/unblock pair. What "
    "this does NOT include is anything that applies, messages a person, or "
    "reveals a contact; those stay refused and are named under "
    "out_of_scope_by_design.",
    "Thirteen writes that reach Uplers, every one confirm-gated and every one "
    "previewing the exact request first. Enumerated exactly under `writes`.",
    "TWO of those thirteen are NOT reversible settings switches and are "
    "censused apart for that reason: revoking Uplers' permission to scan his "
    "Gmail for job-board alerts, and publishing interview feedback, which is "
    "ONE-WAY - no edit route, no delete route. Both preview first; the one-way "
    "one also refuses any company that is not on his live interview list, and "
    "that list is currently empty.",
    "Self-description that can be falsified from OUTSIDE the process: `build` "
    "against `git rev-parse HEAD` on disk, `config.scoring_hash` against the "
    "stamp on a stored score.",
]

WRITE_CENSUS = {
    "counted_by": (
        "EFFECT, never by HTTP verb. A read-shaped POST is counted as a read - "
        "talent/hr/tailor-jobs is one, and uplers_tailored_jobs calls it - so "
        "the numbers below are 'what can change', not 'how many POSTs exist'."
    ),
    "reach_uplers": {
        "requisition": {
            "count": len(REQUISITION_WRITE_TOOLS),
            "tools": list(REQUISITION_WRITE_TOOLS),
            "note": (
                "uplers_apply expresses interest, which on Uplers IS applying "
                "and cannot be undone. uplers_dismiss is genuinely reversible - "
                "Uplers ships an explicit reset_not_interested flag for it - and "
                "a performed dismissal returns the exact call that reverses it."
            ),
        },
        "profile": {
            "count": len(PROFILE_WRITE_TOOLS),
            "tools": list(PROFILE_WRITE_TOOLS),
            "note": (
                "Two writes and the undo each one ships with. All four are "
                "confirm-gated and all four SNAPSHOT BEFORE THEY SEND, because "
                "all four replace a whole field rather than editing one: an "
                "omitted skill is deleted, and a replaced resume is gone from "
                "Uplers. Both pairs go to talent/profile-upsert, the skills half "
                "as JSON and the resume half as multipart."
            ),
        },
        "agent_config": {
            "count": len(AGENT_CONFIG_WRITE_TOOLS),
            "tools": list(AGENT_CONFIG_WRITE_TOOLS),
            "note": (
                "The write half of talent/outreach/*, and ONLY the reversible "
                "part of it. Two are a route pair Uplers ships - block and "
                "unblock name each other in their own UI. The other three "
                "overwrite a settings record that a GET serves back, so each "
                "one READS THE LIVE RECORD FIRST, carries over every field the "
                "caller did not name, snapshots, sends, and then re-reads to "
                "say whether the value actually landed. A 200 is not proof a "
                "value changed. None of the five applies to anything, messages "
                "a person, or reveals a contact."
            ),
            "the_inversion": (
                "Uplers stores the follow-up flags NEGATED - "
                "disabled_followup_gmail: false means gmail is ON. These tools "
                "take natural polarity (gmail_enabled) and the negation happens "
                "exactly once, in outreach_write.to_disabled. A second negation "
                "anywhere cancels the first and switches OFF the channel the "
                "caller asked to switch ON, silently, with a 200 coming back."
            ),
        },
        "consent_and_one_way": {
            "count": len(CONSENT_AND_ONE_WAY_WRITE_TOOLS),
            "tools": list(CONSENT_AND_ONE_WAY_WRITE_TOOLS),
            "note": (
                "THE TWO THAT ARE NOT REVERSIBLE SETTINGS SWITCHES, filed apart "
                "from agent_config for exactly that reason - that group's whole "
                "claim is that everything in it can be put back. "
                "uplers_revoke_email_scan withdraws Uplers' standing permission "
                "to scan his job-board alert emails: reversible on their side (a "
                "POST to the same URL re-grants) but a PERMISSION rather than a "
                "setting, and re-granting starts a FRESH scan rather than "
                "resuming. uplers_submit_interview_feedback is genuinely ONE-WAY "
                "and is the only tool here that reaches a one-way route in that "
                "namespace at all. Both are confirm-gated, both read live first, "
                "both snapshot, both re-read."
            ),
            "what_the_revoke_does_not_do": (
                "MEASURED, and it is narrower than it sounds. It stops FUTURE "
                "scans only - Uplers' own success copy is future tense. NO ROUTE "
                "ANYWHERE DELETES ALREADY-INGESTED SCAN DATA: complete negative "
                "search, the only three DELETE routes under talent/outreach/* "
                "are this consent, settings/disabled-companies/{id} and "
                "external-apply-pending-jobs/{id}. And it does NOT disconnect "
                "Gmail - that is a separate grant on talent/account/gmail/"
                "disconnect, which this server does not build."
            ),
            "the_one_way_one_has_no_undo_at_all": (
                "There is no edit route and no delete route for submitted "
                "interview feedback anywhere in Uplers' product. The snapshot is "
                "LOCAL ONLY and cannot retract what Uplers received. Its guard 4 "
                "is therefore stricter than the others': a company_id that is "
                "not on the live interview list is REFUSED rather than posted. "
                "MEASURED: that list currently holds ZERO companies, so every "
                "call refuses today - which is the tool working."
            ),
        },
    },
    "reach_the_shared_config": {
        "count": len(SHARED_CONFIG_WRITE_TOOLS),
        "tools": list(SHARED_CONFIG_WRITE_TOOLS),
        "note": (
            "The only tool here that writes a file OTHER servers read. It writes "
            "the `candidate` section of jobhunt.json and nothing else - never "
            "`scoring`, never a sibling server's block - and jobcore's "
            "apply_patch enforces that independently of this server."
        ),
    },
    "local_state_only": {
        "tools": list(LOCAL_STATE_ONLY_TOOLS),
        "note": (
            "Filed apart from the sets above so those stay exact. THE LABEL "
            "OVERSTATES TWO OF THE THREE: only uplers_sync_profile_from_uplers "
            "writes anything, and it writes local disk FROM Uplers rather than "
            "the other way - his Uplers profile is the authoritative direction "
            "and there is no counterpart going back. The two list_*_snapshots "
            "tools are PURE DISK READS, filed beside their siblings so the "
            "restore surface reads as one group."
        ),
    },
    "not_a_census_of_local_disk": (
        "Plenty of tools outside `local_state_only` write local state - "
        "uplers_sync_index writes the index, save/unsave the shortlist, "
        "track/update_status the tracker, the alert tools their alerts, "
        "uplers_set_profile the local profile, uplers_logout the session. None "
        "of them can reach Uplers, which is why none is counted above. The sets "
        "above answer 'what can change outside this machine', not 'what touches "
        "the disk'."
    ),
    "gate": (
        "Every write that reaches Uplers performs NOTHING without confirm=True "
        "and otherwise returns a preview of the exact request it would send."
    ),
}

IRREVERSIBLE = {
    "no_undo_anywhere_in_uplers": {
        "tools": list(IRREVERSIBLE_TOOLS),
        "why": (
            "Expressing interest on Uplers IS applying: their own analytics "
            "label the two call sites 'Single Opportunity - Apply' and 'All "
            "opportunity - Apply', and once it lands the button is disabled and "
            "reads 'Applied'. THERE IS NO WITHDRAW, NO CANCEL AND NO UN-APPLY "
            "ANYWHERE IN THEIR PRODUCT - a complete negative search over 13.4 MB "
            "of their bundle: 'Withdraw' 0 hits, 'Cancel Application' 0, "
            "'unapply' 0. The only thing that retracts an application on Uplers "
            "is deactivating the whole account, which is where their own copy "
            "mentions it. Treat every apply as final."
        ),
        "recoverable_by": "nothing",
    },
    "one_way_door_on_uplers_recoverable_only_locally": {
        "tools": list(ONE_WAY_DOOR_TOOLS),
        "why": (
            "UPLERS KEEPS NO PREVIOUS COPY OF THE RESUME. Verified as absences "
            "across their whole corpus - resume_history 0 hits, resume_versions "
            "0, previous_resume 0, old_resume 0, resume_archive 0 - and the "
            "download route takes one parameter and no version, so it always "
            "returns the CURRENT resume. No history, no versions, no revert "
            "route on their side."
        ),
        "recoverable_by": (
            "A PRE-FLIGHT SNAPSHOT TO LOCAL DISK, taken by this server before "
            "the write is sent, and it is the only rollback in existence. "
            "uplers_server.resume_write REFUSES TO SEND AT ALL when the snapshot "
            "cannot be taken, because after the replacement the old document is "
            "unreachable forever. uplers_restore_resume replays it."
        ),
        "caveat": (
            "The snapshot restores the FILE, not the RECORD. The undo is a fresh "
            "upload, so server-side identity is new, and whether Uplers "
            "re-parses the resume, re-scores him, notifies a recruiter or "
            "touches an already-submitted application is UNRESOLVED - every "
            "preview prints that verbatim rather than summarising it."
        ),
    },
    "why_two_lists_and_not_one": (
        "They are different safety classes, and flattening them would have to "
        "lie in one direction or the other: promise a rollback for uplers_apply "
        "that does not exist, or deny the local one for uplers_replace_resume "
        "that does. `irreversible_tools` stays exactly the first list, which is "
        "what every existing caller of this tool already reads."
    ),
}

OUT_OF_SCOPE_BY_DESIGN = [
    {
        "what": (
            "A second autonomous applier. This server does not have one and "
            "will not grow one."
        ),
        "why": (
            "He is ALREADY PAYING for Uplers' own autonomous applier - measured, "
            "not inferred: plan 2, auto_run 1, outreach_mode 'auto'. The reason "
            "is not 'apply cannot be undone': Naukri has no withdraw either and "
            "this family shipped an agent there. It is that a second "
            "UNCOORDINATED agent applying from one account, against a "
            "250-requisition board, through a single intermediary who gates "
            "every future match, while the vendor's own agent already holds the "
            "wheel, is the wrong answer at any quality of implementation."
        ),
    },
    {
        "what": (
            "CONNECTING THE LINKEDIN OUTREACH CHANNEL. Not refused on taste - "
            "IMPOSSIBLE from here, and this is the finding rather than a "
            "shortfall. It is the highest-value thing on this account and it "
            "needs sixty seconds in HIS OWN BROWSER."
        ),
        "why": (
            "POST talent/account/linkedin/connect carries {email, password} - "
            "HIS ACTUAL LINKEDIN PASSWORD - to Uplers' API, followed by a "
            "second stage on talent/account/linkedin/verify keyed on an "
            "auth_type of either 'code_required' (a 2FA code sent to his email, "
            "phone or authenticator) or 'linkedin_app_approval' (approve the "
            "request in the LinkedIn app). VERIFIED from the rendered form in "
            "their bundle: input#agent-onb-li-email and "
            "input#agent-onb-li-password, placeholder 'Enter your LinkedIn "
            "password'. Their own card prints 'We never see your password' "
            "directly above that form. "
            "THIS SERVER NEVER HANDLES A PASSWORD - the same rule uplers_login "
            "already follows, which is why login opens a browser window and he "
            "signs in himself. It would also be a THIRD party's credential, not "
            "Uplers', handed to a vendor; his LinkedIn is a paid Premium Career "
            "account and sharing credentials is against LinkedIn's own terms. "
            "Automating it is refused at every one of those layers "
            "independently. He connects it on the Happpy Agent onboarding card "
            "under 'Enable linkedin Outreach'."
        ),
        "measured": (
            "The channel is dead at both ends and four separate routes agree: "
            "outreach-step says linkedin_connected false and linkedin_template "
            "false, get-message-templates returns the empty string for the "
            "linkedin template, preview-config carries its own "
            "linkedin_connected false, and talent/account/status omits linkedin "
            "entirely rather than reporting it false. Uplers' own failure text "
            "names that dead channel on 11 of the 16 failed agent runs."
        ),
    },
    {
        "what": (
            "What is left of the refused half of talent/outreach/* - "
            "store-employee-requests, reveal-email, discard-job, "
            "auto-run-request, consent-auto-run, the POST (grant) arm of "
            "consent-email-job-scan, and the five commercial claim routes. The "
            "REVERSIBLE half is built; see writes."
        ),
        "narrowed_2026_08_25": (
            "TWO NAMES CAME OFF THIS LIST and the entry is edited rather than "
            "left standing, because a refusal that names something now built is "
            "worse than no refusal. `interview-feedback` and the DELETE (revoke) "
            "arm of `consent-email-job-scan` are now built - see the "
            "`consent_and_one_way` group under writes. "
            "WHAT CHANGED THE ANSWER IS DIFFERENT FOR EACH, and neither was a "
            "new measurement overturning an old one: this refusal already SAID "
            "the consent flips were refused on WHOSE CALL IT IS rather than on "
            "safety, and a refusal on that ground is answered by giving him the "
            "control, gated, not by keeping it. So the revoke was built and the "
            "GRANT was not: re-granting starts a fresh mailbox scan, which is a "
            "decision the same size as stopping one and needs its own preview. "
            "`interview-feedback` is the harder case and was admitted on a "
            "narrower argument: it is ONE-WAY and stays one-way, so it is built "
            "with a guard the reversible five do not carry - it refuses any "
            "company that is not on the live interview list, which currently "
            "holds ZERO companies, so it refuses every call today. The judgement "
            "was that a one-way write behind a preview, a confirm gate and a "
            "membership check is a smaller hazard than the same review published "
            "from a browser form with no preview at all. `store-employee-"
            "requests`, `reveal-email`, `discard-job`, `auto-run-request`, the "
            "grant arm and the five claim routes are UNMOVED."
        ),
        "why": (
            "The line moved from 'the namespace' to 'the effect', because one "
            "ruling was covering 31 routes of very different character. What "
            "was built is reversible AND reads its prior state back: two are a "
            "route pair Uplers ships, three overwrite a settings record a GET "
            "serves. What stays refused is refused for its own reason. "
            "store-employee-requests IS the outreach send, and Uplers' own UI "
            "copy says it cannot be undone. reveal-email spends a credit to "
            "expose a person's address. auto-run-request queues the paid agent "
            "at a job, which is the second-applier problem by another door. "
            "consent-auto-run turns the autonomous applier itself on and off, "
            "and the GRANT arm of consent-email-job-scan starts a fresh mailbox "
            "scan - both are his decision, not this server's, and the grant is "
            "the half that starts something rather than stops it. The claim "
            "routes alter a live paid subscription. "
            "NINE ONE-WAY ROUTES HAVE NO CONSTANT in endpoints.py - they are "
            "recorded there as prose, because a constant is an invitation to "
            "call it. That was ten until 2026-08-25; interview-feedback is the "
            "one deliberate exception and it has a constant because it is now "
            "CALLED, which is argued at EP_INTERVIEW_FEEDBACK itself. "
            "consent-auto-run appears in endpoints.py zero times and still does. "
            "EP_CONSENT_EMAIL_JOB_SCAN exists and is now REFERENCED - by "
            "uplers_server/consent_write.py and by nothing else, which "
            "tests/test_agent_tools.py asserts by AST across every module in the "
            "package. Until 2026-08-25 that test asserted the opposite, that "
            "nothing referenced it at all; it went red the moment the route was "
            "wired, which is what it was built to do, and it was narrowed in the "
            "same commit rather than deleted."
        ),
    },
    {
        "what": (
            "The ORDERING half of the paid candidate SKUs: talent/tailor/"
            "order/create, order/capture, refund-request and the transform "
            "arm; every non-dashboard arm of talent/resume-health-check/*; and "
            "the referral agent (talent/referral-agent/*) entire. The THREE "
            "READS were built on 2026-08-25; see uplers_resume_health and "
            "uplers_tailored_resumes."
        ),
        "why": (
            "The line moved from 'the namespace' to 'the effect', the same way "
            "it moved for talent/outreach/* a day earlier, and for the same "
            "reason: one ruling was covering routes of very different "
            "character. Ordering, transforming and refunding alter a live paid "
            "subscription or spend an attempt, and those stay refused with no "
            "constant in endpoints.py. READING BACK what he has already bought "
            "does neither."
        ),
        "what_overturned_the_read_half": (
            "MEASUREMENT, not argument, and it refuted a specific claim this "
            "register used to make. The old entry reasoned that wrapping these "
            "routes 'would produce tools that fail at runtime' because the "
            "account holds zero tailor credits. MEASURED LIVE 2026-08-25 on "
            "his own session: talent/outreach/get-last-health-check, "
            "talent/resume-health-check/dashboard and talent/tailor/list each "
            "answered HTTP 200 with real data - a resume score of 89, three "
            "history rows, and a plan record. Zero 403s, zero 402s, no credit "
            "gate anywhere on the read side. The credit metering is real and it "
            "gates BUYING a tailored resume; it does not gate reading the check "
            "he has already had. Captured by scripts/capture_skus.py."
        ),
        "is_it_included_in_his_plan": (
            "MEASURED, not assumed, because 'it might be bundled' would change "
            "the answer and only a measurement can settle it. IT IS NOT, and "
            "the reads now corroborate that from a third direction rather than "
            "contradicting it. talent/outreach/agent-plans returns a catalogue "
            "with exactly two entries, id 1 (Starter, 30 days) and id 3 (Elite, "
            "90 days), and his outreach-step reads plan: 2 - a plan that is not "
            "in the catalogue at all. The metering agrees from two directions: "
            "outreach-step reads credit_plan 0, credit_left 0, credit_added 0, "
            "and preview-config independently carries plan.paid true, "
            "plan.expired false, plan.credit_left 0. talent/tailor/list now "
            "adds a third: plan_active 0, remaining_days 0, and a plan_end_date "
            "of 2026-08-11 already past. So the tailor surface is credit-metered, "
            "he holds zero credits, and his tailor plan has lapsed - which is "
            "exactly why the ordering routes stay unbuilt and exactly what the "
            "read tools report."
        ),
    },
    {
        "what": (
            "find-similar-job and talent-matchmake. Recorded, deliberately not "
            "built."
        ),
        "why": (
            "Two reasons, both about these routes rather than about POSTs in "
            "general. (1) find-similar-job sends HIS EMAIL ADDRESS in the body "
            "to get back a list. (2) The payoff is near zero: this server "
            "already indexes all 250 requisitions locally, so 'similar to this "
            "one' is answerable offline by uplers_rank_opportunities against a "
            "record already held - with jobcore's scoring, comparable across "
            "servers, rather than Uplers' opaque one. A third reason, that it "
            "would be the first non-write POST here, WAS WITHDRAWN ON 2026-08-24 "
            "as false: talent/hr/tailor-jobs is already a read-shaped POST and "
            "predates the claim."
        ),
    },
    {
        "what": "talent/hr/cancel-opportunity.",
        "why": (
            "DEAD CODE in the build that was read - no live call site - so its "
            "real behaviour is unverified, and it is not the withdraw its name "
            "suggests. Building an un-apply out of a route nobody has seen fire, "
            "against a product that has no un-apply, would be inventing a "
            "promise this server cannot keep."
        ),
    },
    {
        "what": "talent/recommendations, and the name is the trap.",
        "why": (
            "It is NOT a job-recommendations feed. Its body is {key: 'rnr', "
            "role: '<job title>'} and its single caller in 13.4 MB is the "
            "PROFILE EXPERIENCE EDITOR: it returns suggested bullet-point text "
            "for a CV entry. Built as a jobs feed it would have produced a tool "
            "that silently returned the wrong kind of thing."
        ),
    },
]

KNOWN_LIMITS = {
    "measured_404": {
        "routes": list(endpoints.MEASURED_404),
        "measured_on": "2026-08-23",
        "detail": (
            "Both answered HTTP 404 on a LIVE session with a real "
            "outreach_hr_id taken off an agent-tailor-activity row - the same id "
            "that answered 200 on every other route in that ring. Both had been "
            "listed as buildable GET reads off the bundle inventory; a path that "
            "appears in the bundle is not a path the API serves."
        ),
        "the_open_question": (
            "THE PARAMETER SPACE, NOT THE SESSION. The session was good and the "
            "id was good, so re-probing after a fresh login is not the retry "
            "that could change this answer - finding the identifier or query "
            "these two actually want is. Recorded so nobody re-runs the probes."
        ),
    },
    "resolved_identifier_space": {
        "routes": ["get-company-salary-data", "get-company-detail"],
        "resolved_on": "2026-08-24",
        "the_id_space": (
            "`hr_id` is the requisition row's PLAIN NUMERIC `id`. Found by "
            "reading where the value is PRODUCED rather than where it is "
            "consumed: the estimated-salary-pill component takes `hrData.id` "
            "and sends '?hr_id='.concat(id). Proven live by a one-row control - "
            "the SAME requisition answers 200 with its `id` and 400 'No HR "
            "found..' with its `HR_Number`."
        ),
        "entitlement_answered_and_it_is_not_one": (
            "NOT an entitlement. Every live probe answered 200 and not one "
            "answered 403. The dedicated 403 branch exists, but this account is "
            "never refused by it, so reading that branch as 'strong evidence of "
            "an account entitlement' was an inference the measurement did not "
            "support."
        ),
        "why_the_earlier_probes_all_404d": (
            "WRONG ROWS, NOT WRONG ID SPACE. The pill mounts only behind "
            "'confidential' === cost_string.toLowerCase() && "
            "!is_partner_company. A row failing that gate answers 400 whatever "
            "identifier you send it, so re-running the six probes could never "
            "have moved the answer."
        ),
        "a_trap_in_the_data": (
            "`is_partner_company` is POLYMORPHIC - boolean on most "
            "authenticated feed rows, a DATE STRING on others, and a date "
            "string on every row of the public index. A truthiness test "
            "classifies every date-valued row as 'partner', which produced a "
            "confident and completely wrong 'no row qualifies' during the "
            "investigation that closed this. Treat a truthy non-boolean as "
            "UNKNOWN."
        ),
        "what_it_returns": (
            "has_salary_data, company_salary_p25 / _p75, a formatted "
            "company_salary_range, and company_matches. 3 of 6 gate-satisfying "
            "rows carried real percentiles. The gate fires exactly when "
            "cost_string is 'Confidential' - the case where the board shows no "
            "pay at all - so it is an estimated band for precisely the "
            "requisitions whose salary is otherwise hidden. No tool calls it; "
            "that is a scope decision, not a safety one."
        ),
    },
}


# ------------------------------------------------------------ tool 17 ---


@mcp.tool()
async def uplers_server_info() -> ServerInfo:
    """What code THIS process is running. Check it before debugging behaviour.

    HOW TO USE IT, and it is one comparison: take `build.code.commit` and run
    `git rev-parse HEAD` in the uplers checkout. If they DIFFER, this process
    predates the commit on disk - it is stale, it is still executing the old
    code, and debugging its behaviour is pointless until the MCP host restarts
    it. If they MATCH, the running code is the committed code and a surprising
    result is a real bug rather than a ghost. `build.code.dirty` says whether
    the tree carried uncommitted edits when this process started, because a
    commit alone answers nothing about a modified working tree.

    `build.jobcore` is the SAME check against the shared scoring library, and
    it is not redundant: this server's fit scores are jobcore's, so a stale
    jobcore changes every number here while `build.code` reads perfectly
    current. Both must match disk before a scoring complaint means anything.

    The stamps are frozen at import ON PURPOSE. A commit made after this
    process started does not move them - that is what makes the comparison
    able to detect staleness at all, and it is why `build.process.started_at`
    is reported beside them.

    `config.scoring_hash` is the other comparison worth making: it is the value
    stamped on every scored result, so a stored score whose stamp differs was
    produced by arithmetic no longer in force.

    THE OTHER HALF OF THIS PAYLOAD IS WHAT THIS SERVER CAN AND CANNOT DO, and
    it is here for the same reason the commit is: so a claim about this server
    can be checked without reading its source. `capabilities` groups the 53
    tools. `writes` is the exact write census, counted by EFFECT rather than by
    HTTP verb, and it is the load-bearing one - a new write that reaches Uplers
    without appearing there is the staleness this tool exists to catch, which
    is why tests/test_server_info.py pins every name in it against the
    registered tool list and every count against tests/test_tools.py.
    `irreversible` splits two safety classes that must not be flattened: what
    has no undo anywhere in Uplers' product, and what is a one-way door on
    THEIR side that only a local pre-flight snapshot can reverse.
    `out_of_scope_by_design` is the standing refusals with their reasons, and
    `known_limits` is what has been MEASURED unreachable, recorded so nobody
    re-runs the probes.

    Those five are DECLARATIONS read from module constants, not derived at call
    time. That is deliberate: this is the tool you call when the server is
    already under suspicion, so it must not run the machinery under suspicion
    to answer.

    Costs nothing - it reads module constants and touches neither git, the
    network, nor the database.
    """
    bound = _bind()
    ld = bound.loaded
    return ServerInfo(
        server={"name": "uplers", "version": __version__},
        build=buildinfo_mod.build_block(),
        config={
            "source": policy_mod.display_path(ld.source),
            "policy_rev": ld.policy_rev,
            "policy_hash": ld.policy_hash,
            "scoring_hash": ld.scoring_hash,
        },
        tiers=(
            "PUBLIC tools need no account (uplers_sync_index, uplers_daily_brief, "
            "uplers_rank_opportunities and the rest of the board readers); "
            "AUTHENTICATED tools read his Uplers account and need uplers_login "
            "first (uplers_my_feed, uplers_my_pipeline, uplers_my_profile, "
            "uplers_apply)."
        ),
        irreversible_tools=list(IRREVERSIBLE_TOOLS),
        capabilities=list(CAPABILITIES),
        writes=WRITE_CENSUS,
        irreversible=IRREVERSIBLE,
        out_of_scope_by_design=list(OUT_OF_SCOPE_BY_DESIGN),
        known_limits=KNOWN_LIMITS,
    )


# ==========================================================================
# THE AUTHENTICATED TIER
#
# Everything above this line reads Uplers' PUBLIC catalogue and needs no
# account. Everything below reads HIS account, and the difference is the point:
# the public board shows what Uplers is hiring for, his account shows what
# Uplers is doing about HIM - which requisitions he has been matched to, what
# their recruiters have moved to interview, and what his profile looks like to
# the people making that call.
#
# Three facts shape every tool here.
#
# 1. Auth is `Authorization: Bearer <token>`, where the token comes from the
#    browser's localStorage. Playwright opens the window; after that the
#    browser is out of the data path entirely, exactly as the public tier
#    keeps it out.
# 2. Sessions are SHORT. Re-login is close to a daily event, so every read
#    below turns an expired session into "run uplers_login()" rather than into
#    an empty list. An empty list here always means "nothing matched".
# 3. Expressing interest CANNOT BE UNDONE. See uplers_apply.
# ==========================================================================


def _session_store() -> SessionStore:
    return SessionStore()


def _talent_client() -> TalentClient:
    """A client that reads the token live, so a re-login is picked up at once."""
    return TalentClient(_session_store().token)


def _feed_params(
    *,
    page: int,
    page_size: int,
    sort: str,
    experience: str | None,
    roles: str | None,
    locations: str | None,
    modes: list[str] | None,
    count: bool = False,
) -> dict:
    """Build the query Uplers' own jobs board builds.

    Every name and every encoding here is copied from the bundle's query
    builder, including the two that are easy to get wrong: `experience` is a
    "min,max" RANGE STRING rather than a number, and `engagements` is a
    JSON-ENCODED ARRAY OF OBJECTS rather than a plain list.
    """
    import json as _json

    params: dict = {
        "pagination": page_size,
        "page": page,
        "is_count": "1" if count else "0",
        "sort_field": sort,
    }
    if experience:
        params["experience"] = experience
    if roles:
        params["roles"] = roles
    if locations:
        params["locations"] = locations
    if modes:
        params["engagements"] = _json.dumps([{"type": mode} for mode in modes])
    return params


def _validate_sort(sort: str) -> str:
    if sort not in endpoints.SORT_FIELDS:
        raise UplersError(
            "sort must be one of %s (got %r)." % (list(endpoints.SORT_FIELDS), sort)
        )
    return sort


def _validate_modes(modes: list[str] | None) -> list[str] | None:
    if not modes:
        return None
    valid = {mode.lower(): mode for mode in endpoints.ENGAGEMENT_MODES}
    out = []
    for mode in modes:
        key = str(mode).strip().lower()
        if key not in valid:
            raise UplersError(
                "mode %r is not one of %s. Note Uplers says 'Onsite', not 'Office', "
                "on this API." % (mode, list(endpoints.ENGAGEMENT_MODES))
            )
        out.append(valid[key])
    return out


def _profile_or_none(bound=None):
    """The effective profile for scoring, or None when none is usable.

    A missing profile must not take a read down: the rows are still worth
    having unscored, and the note says why the scores are absent.
    """
    try:
        return policy_mod.effective_profile(prof.require(), bound)[0]
    except prof.ProfileError:
        return None


async def _paged_read(
    client: TalentClient,
    route: str,
    *,
    params: dict,
    pages: int,
    profile,
    bound=None,
    explain: bool = False,
) -> tuple[list, dict, list[str]]:
    """Fetch `pages` pages of a paginator, stopping at the last real page."""
    rows: list = []
    notes: list[str] = []
    meta: dict = {}
    for offset in range(max(1, pages)):
        page_params = dict(params)
        page_params["page"] = params.get("page", 1) + offset
        payload = await client.get_json(route, page_params)
        page_rows, page_meta, page_notes = talent_shape.rows_from(
            payload, route=route, profile=profile, bound=bound, explain=explain
        )
        rows.extend(page_rows)
        notes.extend(note for note in page_notes if note not in notes)
        meta = page_meta or meta
        last = page_meta.get("last_page")
        if last is not None and page_params["page"] >= last:
            break
    return (rows, meta, notes)


# --------------------------------------------------------------- login ----


@mcp.tool()
async def uplers_login(wait_seconds: int = 300) -> LoginResult:
    """Sign in to Uplers. Opens a real browser window; you type, nothing else does.

    A window opens at Uplers' login page and STAYS OPEN until Uplers itself
    confirms a signed-in session - not until a token appears. Those are
    different things and the difference matters: Uplers hands out an anonymous
    `guest_token` to signed-out visitors, so "a token exists" is true before
    you have typed anything. This tool only returns success when a real
    authenticated request comes back with your profile in it.

    The profile directory is persistent, so if you are already signed in this
    returns in about a second without asking for anything.

    Sessions here are SHORT-LIVED - expect to run this roughly daily. That is
    a property of Uplers, not of this server.

    Call it when: uplers_auth_status() says false, or any authenticated tool
    tells you the session expired.

    Args:
        wait_seconds: how long the window stays open for you to sign in.
    """
    store = _session_store()
    try:
        result = await auth_mod.login_via_browser(store, wait_seconds=wait_seconds)
    except auth_mod.BrowserUnavailable as exc:
        return LoginResult(authenticated=False, reason=str(exc), error="browser_unavailable")
    return LoginResult(**{key: value for key, value in result.items() if key != "profile_dir"})


@mcp.tool()
async def uplers_auth_status() -> AuthStatus:
    """Are we actually signed in to Uplers? Measured, not guessed.

    Spends one real request against an endpoint that returns 401 when logged
    out, so a `false` here is a measurement rather than a claim about whether
    a file exists on disk. `authenticated` can be:

      true   - a request came back carrying your profile.
      false  - Uplers rejected the session. Run uplers_login().
      null   - could not be determined (network, an unexpected response). NOT
               the same as false, and not a reason to sign in again yet.

    Never returns the token, a prefix of it, or its length.
    """
    store = _session_store()
    described = store.describe()
    async with _talent_client() as client:
        status = await session_mod.check_auth(client)

    notes: list[str] = []
    if described.get("expired"):
        notes.append("The stored token's own expiry has passed.")
    if status.get("authenticated") is True and not described.get("expires_at"):
        notes.append(
            "Uplers' token carries no readable expiry, so the only way to know it is "
            "still live is to ask - which is what this tool just did."
        )
    return AuthStatus(
        authenticated=status.get("authenticated"),
        reason=status.get("reason"),
        signed_in_as=status.get("signed_in_as"),
        token_present=described.get("token_present"),
        token_format=described.get("token_format"),
        saved_at=described.get("saved_at"),
        expires_at=described.get("expires_at"),
        expired=described.get("expired"),
        profile_completion_percentage=status.get("profile_completion_percentage"),
        checked_against=status.get("checked_against"),
        error=status.get("error"),
        notes=notes,
    )


@mcp.tool()
async def uplers_session_info(verify_live: bool = True) -> dict:
    """How long your Uplers session has left, and what happens when it ends.

    The one thing to read carefully is `credential.expiry_is_authoritative`,
    which on Uplers is always FALSE. The stored token is a JWT and its `exp`
    claim sits about six months out - and that date is a CEILING THE TOKEN
    CLAIMS, not a promise Uplers keeps. They revoke server-side far sooner;
    expect to sign in again roughly daily. Reading that date as a runway is
    the single way to be badly wrong about this server.

    `authenticated` is measured, never inferred, and it can honestly be null:

      true   - the probe route answered with your profile.
      false  - Uplers refused the stored token. Run uplers_login().
      null   - no verdict was obtained. NOT a refusal, and not a reason to
               sign in again yet; `live_check.why_not` says what happened.

    `expired` is null too when the expiry is not knowable - a Sanctum or
    opaque token keeps its expiry on Uplers' servers, and "I cannot tell" is
    not "it is fine".

    There is no uplers_reauth, on purpose: this platform has nothing durable
    to renew FROM, and `renewal.why` gives the evidence. Never returns the
    token, a prefix of it, or its length.

    Args:
        verify_live: True spends one real request for a measured verdict.
            False is free - no network, no browser - and `authenticated` comes
            back null with the reason recorded.
    """
    store = _session_store()
    if not verify_live:
        return session_mod.session_info_offline(
            store,
            why_no_live_check=(
                "not attempted: this call asked for the offline answer, so no "
                "request was made and no verdict exists to report."
            ),
            attempted=False,
        )
    try:
        async with _talent_client() as client:
            return await session_mod.session_info(store, client)
    except Exception as exc:  # pragma: no cover - defensive
        # check_auth already turns a network failure into authenticated=None,
        # so reaching here means the client could not even be built. The
        # offline facts are still worth having, and they are what the operator
        # asked for underneath the question.
        return session_mod.session_info_offline(
            store,
            why_no_live_check=(
                "the live check could not be run at all: %s"
                % policy_mod.relativise_paths(
                    "%s: %s" % (type(exc).__name__, exc), [str(store.path)]
                )
            ),
            attempted=True,
        )


@mcp.tool()
async def uplers_logout() -> dict:
    """Delete the stored Uplers token from this machine. Cannot fail loudly.

    LOCAL ONLY. It removes this server's copy of the bearer token and nothing
    else: you are NOT signed out on Uplers' side, and the persistent browser
    profile is left exactly as it is, so uplers_login() usually signs back in
    within seconds and without a password.

    The `authenticated: false` it returns is the one false in this server that
    is not a measurement, and it is honest for a specific reason: with no
    credential left there is no authenticated request that CAN be made from
    here. `reason` says so rather than leaving you to assume it.

    Use it when handing the machine over, or to force the next call to
    re-authenticate. The public tier is untouched and keeps working.
    """
    return session_mod.logout_report(_session_store())


# --------------------------------------------------------------- reads ----


@mcp.tool()
async def uplers_my_feed(
    page: int = 1,
    pages: int = 1,
    page_size: int = 12,
    sort: str = "relevance",
    experience: str | None = None,
    roles: str | None = None,
    locations: str | None = None,
    modes: list[str] | None = None,
    score: bool = True,
    explain: bool = False,
) -> TalentFeed:
    """YOUR personalised Uplers opportunity feed. Needs a signed-in session.

    This is not the public catalogue: it is the board as Uplers shows it to
    you, ordered by their own relevance model, and each row carries what you
    have already done about it (applied / saved / dismissed) plus the ids the
    write tools need.

    Rows are scored with the same jobcore scorer the rest of this server uses,
    so a score here is directly comparable with uplers_rank_opportunities()
    and with the Naukri server.

    Args:
        page: 1-based first page to fetch.
        pages: how many consecutive pages to fetch. Stops early at the last page.
        page_size: rows per page. Uplers' own board uses 12.
        sort: "relevance" (Uplers' model) or "created_at" (newest first).
        experience: a RANGE STRING, not a number - e.g. "4,6" for 4-6 years.
            Valid bands: 0,2 / 2,4 / 4,6 / 6,8 / 8,10 / 10,12 / 12,14.
        roles: comma-joined role ids. Get them from uplers_filter_options("role").
        locations: comma-joined location ids, from uplers_filter_options("location").
        modes: any of "Remote", "Hybrid", "Onsite". Note Uplers says ONSITE,
            not "Office", on this API.
        score: compute fit scores against your local profile.
        explain: show how each of those scores was reached. The one thing this
            surface can tell you that no other can: Uplers ordered these rows
            by THEIR relevance model, so an explained row lets you see where
            their idea of a match and jobcore's actually part company. Costs a
            block per row across every page fetched, so keep `pages` small.
            Does nothing when score=False - an unscored row has no arithmetic.
    """
    sort = _validate_sort(sort)
    modes = _validate_modes(modes)
    bound = _bind()
    profile = _profile_or_none(bound) if score else None
    params = _feed_params(
        page=page,
        page_size=page_size,
        sort=sort,
        experience=experience,
        roles=roles,
        locations=locations,
        modes=modes,
    )

    async with _talent_client() as client:
        rows, meta, notes = await _paged_read(
            client, endpoints.EP_OPPORTUNITIES, params=params, pages=pages,
            profile=profile, bound=bound, explain=explain,
        )
        total = meta.get("total")
        if total is None:
            # Uplers reports the count on a separate call with is_count=1.
            try:
                counted = await client.get_json(
                    endpoints.EP_OPPORTUNITIES,
                    _feed_params(
                        page=page,
                        page_size=page_size,
                        sort=sort,
                        experience=experience,
                        roles=roles,
                        locations=locations,
                        modes=modes,
                        count=True,
                    ),
                )
                if isinstance(counted, dict):
                    total = counted.get("jobs_count")
            except TalentError as exc:
                notes.append("Could not read the total count: %s" % exc)

    if score and profile is None:
        notes.append(
            "Rows are unscored: no usable local profile. Set one with "
            "uplers_set_profile() to get fit scores here."
        )
    return TalentFeed(
        rows=rows,
        returned=len(rows),
        page=meta.get("page") or page,
        last_page=meta.get("last_page"),
        total=total,
        pages_fetched=min(pages, max(1, (meta.get("last_page") or pages) - page + 1)),
        source=endpoints.EP_OPPORTUNITIES,
        filters_applied={
            key: value
            for key, value in {
                "sort": sort,
                "experience": experience,
                "roles": roles,
                "locations": locations,
                "modes": modes,
            }.items()
            if value
        },
        scored_against=_profile_summary(profile, bound) if profile else None,
        notes=notes,
    )


@mcp.tool()
async def uplers_my_pipeline(
    page: int = 1, pages: int = 3, score: bool = False, explain: bool = False
) -> PipelineResult:
    """Your ACTUAL Uplers pipeline - the applications their recruiters are working.

    This is the authoritative record, unlike uplers_list_tracked(), which only
    holds what you told this server you did. Where the two disagree, this one
    is right: `uplers_status` and `uplers_badge` come from Uplers' own
    workflow ("Interviewed", "Slots Given", "Interview Scheduled").

    Use it: to see what is actually moving, and before chasing anything.

    Args:
        page: 1-based first page.
        pages: how many consecutive pages to fetch.
        score: also compute fit scores. Off by default - you already applied,
            so the score is rarely the question here.
        explain: show the arithmetic behind those scores. Rarer still than the
            score itself, and honest about why: this is the retrospective
            surface, so the only real use is auditing why you applied to
            something that has since gone quiet. Needs score=True; on its own
            it adds nothing, because nothing was scored.
    """
    bound = _bind()
    profile = _profile_or_none(bound) if score else None
    async with _talent_client() as client:
        rows, meta, notes = await _paged_read(
            client,
            endpoints.EP_MY_OPPORTUNITIES,
            params={"pagination": 10, "page": page},
            pages=pages,
            profile=profile,
            bound=bound,
            explain=explain,
        )
    return PipelineResult(
        rows=rows,
        returned=len(rows),
        page=meta.get("page") or page,
        last_page=meta.get("last_page"),
        pages_fetched=min(pages, max(1, (meta.get("last_page") or pages) - page + 1)),
        by_status=talent_shape.tally(rows, "uplers_status"),
        by_badge=talent_shape.tally(rows, "uplers_badge"),
        notes=notes,
    )


@mcp.tool()
async def uplers_get_opportunity_live(hr_number: str, compare_public: bool = False) -> FieldReport | OpportunityDetail:
    """One requisition as YOUR account sees it, optionally diffed against the public record.

    The authenticated view of a job can carry fields the public endpoint does
    not - your own application state, matcher information, ids the write tools
    need. `compare_public=True` reports exactly which fields those are, which
    is the honest way to answer "is holding a session actually worth it".

    Args:
        hr_number: the requisition id, e.g. "HR130826031902".
        compare_public: return a field-level diff against the public record
            instead of the job detail.
    """
    hr_number = _validate_hr(hr_number)
    async with _talent_client() as client:
        payload = await client.get_json(endpoints.EP_SINGLE_HR, {"hr_number": hr_number})

    if not isinstance(payload, dict) or not payload:
        raise TalentError(
            "%s returned an empty response for %s. This is NOT 'no such job' - a "
            "missing job is a 404." % (endpoints.EP_SINGLE_HR, hr_number)
        )
    if talent_shape.is_test_record(payload):
        raise TalentError(
            "%s is one of Uplers' internal test requisitions (is_test_hr); their own "
            "UI discards these." % hr_number
        )

    if not compare_public:
        return to_detail(payload, full_description=True)

    with _open_store() as store:
        public = await _record_or_fetch(store, hr_number)
    report = talent_shape.field_report(payload, public)
    if not report.only_in_authenticated:
        report.notes.append(
            "The authenticated record carries nothing the public one does not. For "
            "THIS requisition, a session buys no extra field."
        )
    return report


@mcp.tool()
async def uplers_tailored_jobs(
    hr_number: str | None = None, score: bool = True, explain: bool = False
) -> TalentFeed:
    """Uplers' own tailored suggestions, optionally anchored to one requisition.

    Distinct from uplers_my_feed(): this is the "jobs like this one" surface
    Uplers computes server-side. With no `hr_number` it returns their general
    tailored set.

    Args:
        hr_number: anchor requisition. Omit for the general tailored set.
        score: compute fit scores against your local profile.
        explain: show the arithmetic behind those scores. These rows are
            Uplers' "jobs like this one" and nothing here says why they were
            suggested, so the block is the only account of the match you get -
            read it against the anchor when a suggestion looks unrelated. The
            set is small, which makes this the cheapest of the row surfaces to
            explain. Does nothing when score=False.
    """
    body = {"HR_Number": _validate_hr(hr_number)} if hr_number else {}
    bound = _bind()
    profile = _profile_or_none(bound) if score else None
    async with _talent_client() as client:
        payload = await client.post_json(endpoints.EP_TAILOR_JOBS, body)

    if not isinstance(payload, dict):
        raise TalentError(
            "%s returned %s, not a JSON object." % (endpoints.EP_TAILOR_JOBS, type(payload).__name__)
        )
    raw_rows = payload.get("data")
    if not isinstance(raw_rows, list):
        raise TalentError(
            "%s returned no `data` array (keys: %s), so no tailored jobs could be "
            "read. This is NOT 'no suggestions'."
            % (endpoints.EP_TAILOR_JOBS, sorted(payload)[:12] or "none")
        )
    rows = [
        talent_shape.to_talent_row(row, profile=profile, bound=bound, explain=explain)
        for row in raw_rows
        if isinstance(row, dict) and not talent_shape.is_test_record(row)
    ]
    return TalentFeed(
        rows=rows,
        returned=len(rows),
        source=endpoints.EP_TAILOR_JOBS,
        filters_applied={"anchor": hr_number} if hr_number else {},
        scored_against=_profile_summary(profile, bound) if profile else None,
    )


@mcp.tool()
async def uplers_my_profile() -> TalentProfileResult:
    """Your REAL Uplers profile - the one recruiters and their matching see.

    Distinct from uplers_get_profile(), which returns the LOCAL profile this
    server scores against. This is the record Uplers' own matching runs on and
    the one you maintain, so where the two differ, this one is right.

    Reports what is there. It does not rate your profile or suggest changes to
    it - what belongs on it is your call, and this server does not know what
    you decided or why.

    Run uplers_compare_profiles() to see where the two differ.
    """
    async with _talent_client() as client:
        payload = await client.get_json(endpoints.EP_PROFILE)
    result = talent_shape.to_talent_profile(payload)
    if result.completion_percentage is not None and result.completion_percentage < 100:
        # Reported as Uplers' number, not as a verdict. Their completeness
        # score counts sections this server has no opinion about, and a profile
        # can be exactly as complete as its owner intends it to be.
        result.notes.append(
            "Uplers' own completeness score for this profile is %s%%."
            % round(result.completion_percentage)
        )
    return result


def _uplers_summary(remote) -> ProfileSummary:
    """Uplers' side of a comparison, counted across all three skill sections."""
    return ProfileSummary(
        years_experience=remote.years_experience,
        location=remote.location,
        skills=len(remote.all_skill_names()) or None,
        notice_period_days=notice_days(remote.notice_period),
    )


@mcp.tool()
async def uplers_compare_profiles() -> ProfileComparison:
    """Where your LOCAL profile has fallen behind your UPLERS profile. Writes nothing.

    Two profiles exist and they do different jobs. Your Uplers profile is the
    one you maintain, the one recruiters read, and the one Uplers' matching
    runs against - it is the SOURCE OF TRUTH. The local data/profile.json
    exists for one reason: fit scores need a candidate to score against.

    So a gap between them is a defect in the LOCAL copy, and the fix flows one
    way: uplers_sync_profile_from_uplers(). Nothing in this server ever writes
    to your Uplers profile.

    The exception is a genuine two-sided disagreement - your headline, your
    years - where neither side is obviously right. Those land in
    `needs_your_decision` and stay there.

    Pay attention to notice period: it is the single most decisive field on
    this board, because most Uplers clients accept only 15-30 days.
    """
    local = _profile_or_none(_bind())
    async with _talent_client() as client:
        payload = await client.get_json(endpoints.EP_PROFILE)
    remote = talent_shape.to_talent_profile(payload)

    sections = {
        "skills": len(remote.skills),
        "primary_skills": len(remote.primary_skills),
        "tools": len(remote.tools),
        "distinct": len(remote.all_skill_names()),
    }

    if local is None:
        return ProfileComparison(
            uplers=_uplers_summary(remote),
            uplers_skill_sections=sections,
            recommendation=(
                "There is no local profile to score against. Build one from your "
                "Uplers profile with uplers_sync_profile_from_uplers() - it already "
                "carries %d distinct skills." % sections["distinct"]
            ),
        )

    agree, differ, only_local, only_uplers, contested = talent_shape.compare_profiles(
        local, remote
    )

    notes: list[str] = [
        "Uplers holds %d distinct skills across three sections: %d in `skills`, "
        "%d in `primaryskills` (the subset their matching weighs), %d in `tools`."
        % (sections["distinct"], sections["skills"], sections["primary_skills"], sections["tools"])
    ]
    if only_uplers:
        notes.append(
            "%d skill(s) are on Uplers and MISSING from the local profile: %s. Every "
            "fit score this server has produced was computed without them, so they "
            "are all understated." % (len(only_uplers), ", ".join(only_uplers[:12]))
        )
    if only_local:
        notes.append(
            "%d skill(s) are on the local profile and not on Uplers: %s. Stated as "
            "a difference, not a gap - what is on your Uplers profile is your "
            "decision. They stay in the local copy so fit scores keep using them."
            % (len(only_local), ", ".join(only_local[:12]))
        )

    if only_uplers:
        recommendation = (
            "Your local profile is behind your Uplers one by %d skill(s). Uplers is "
            "the record; run uplers_sync_profile_from_uplers() to bring the local "
            "copy up to it, then re-score." % len(only_uplers)
        )
    elif contested:
        recommendation = (
            "Skills are in sync. %d field(s) genuinely disagree and neither side is "
            "obviously right - see needs_your_decision. Pass a field to "
            "uplers_sync_profile_from_uplers(also=[...]) to take Uplers' value."
            % len(contested)
        )
    elif differ:
        recommendation = (
            "%d field(s) differ. Uplers is the record, so "
            "uplers_sync_profile_from_uplers() is the fix." % len(differ)
        )
    else:
        recommendation = "The local profile matches your Uplers one on everything comparable."

    return ProfileComparison(
        agree=agree,
        differ=differ,
        needs_your_decision=contested,
        only_local=only_local,
        only_uplers=only_uplers,
        uplers_skill_sections=sections,
        local=_profile_summary(local),
        uplers=_uplers_summary(remote),
        recommendation=recommendation,
        notes=notes,
    )


@mcp.tool()
async def uplers_sync_profile_from_uplers(
    confirm: bool = False,
    also: list[str] | None = None,
    replace_skills: bool = False,
) -> ProfileSyncResult:
    """Bring the LOCAL profile up to your Uplers one. One direction, always.

    Your Uplers profile is authoritative. This copies it into
    data/profile.json so fit scores are computed against the real you. It
    NEVER writes to Uplers - no tool in this server does.

    Skills are UNIONED, not replaced. That is a measured decision, not
    caution: scoring the 243 cached requisitions against your real Uplers
    skill set moved 73 of them and 71 moved UP, but two email-infrastructure
    roles moved DOWN, because your local profile carries seven email skills
    (SMTP, deliverability, bulk email, RabbitMQ) that Uplers does not list. A
    replace would delete real capability and quietly demote every email role.

    Your headline and your years are NOT synced by default - neither side is
    obviously right and that is your call. Name them in `also` to take Uplers'.

    Args:
        confirm: False returns a preview and writes nothing.
        also: contested fields to take from Uplers: "headline", "years_experience".
        replace_skills: discard local-only skills instead of keeping them. Rarely right.
    """
    requested = {str(name).strip().lower() for name in (also or [])}
    unknown = requested - set(talent_shape.CONTESTED_FIELDS)
    if unknown:
        raise UplersError(
            "`also` accepts only %s; got %s. Everything else is synced anyway."
            % (", ".join(talent_shape.CONTESTED_FIELDS), ", ".join(sorted(unknown)))
        )

    async with _talent_client() as client:
        payload = await client.get_json(endpoints.EP_PROFILE)
    remote = talent_shape.to_talent_profile(payload)

    local = _profile_or_none(_bind())
    if local is None:
        local = prof.Profile(source="uplers")

    uplers_skills = remote.all_skill_names()
    if not uplers_skills:
        raise UplersError(
            "Your Uplers profile resolved to zero skills, so there is nothing to "
            "sync. That is far more likely to be a broken read than an empty "
            "profile - check uplers_my_profile() before trusting it."
        )

    current = list(local.skills or [])
    current_keys = {name.strip().lower() for name in current}
    uplers_keys = {name.strip().lower() for name in uplers_skills}

    added = [name for name in uplers_skills if name.strip().lower() not in current_keys]
    local_only = [name for name in current if name.strip().lower() not in uplers_keys]
    if replace_skills:
        merged, removed, kept = list(uplers_skills), local_only, []
    else:
        merged, removed, kept = current + added, [], local_only

    changes: list[FieldChange] = []
    updates: dict = {"skills": merged}

    def take(field: str, new_value, render=str) -> None:
        old_value = getattr(local, field, None)
        if new_value in (None, "", [], {}) or old_value == new_value:
            return
        updates[field] = new_value
        changes.append(
            FieldChange(
                field=field,
                before=render(old_value) if old_value is not None else "(not set)",
                after=render(new_value),
            )
        )

    take("name", remote.name)
    take("location", (remote.preferred_cities or [None])[0] or remote.location)
    take("notice_period_days", notice_days(remote.notice_period))
    # `titles` is synced ONLY from Uplers' own roles list, never derived from
    # the headline. Falling back to the headline would import a contested
    # value through a side door: `titles` biases ranking, so "leave the
    # headline to him" would have been true of one field and false in effect.
    if remote.titles:
        take("titles", remote.titles, render=lambda v: ", ".join(v))
    if "headline" in requested:
        take("headline", remote.headline)
        # A headline he has just accepted is also what he is targeting.
        take("titles", [remote.headline], render=lambda v: ", ".join(v))
    if "years_experience" in requested:
        take("years_experience", remote.years_experience)

    left_for_you = [
        FieldDiff(
            field=field,
            local=str(getattr(local, field, None) or "(not set)"),
            uplers=str(getattr(remote, field, None)),
            note="Not synced. Pass also=['%s'] to take Uplers' value." % field,
        )
        for field in talent_shape.CONTESTED_FIELDS
        if field not in requested
        and getattr(remote, field, None) not in (None, "", [], {})
        and str(getattr(local, field, None) or "").strip().lower()
        != str(getattr(remote, field, None)).strip().lower()
    ]

    notes: list[str] = []
    if kept:
        notes.append(
            "%d local-only skill(s) kept, not deleted: %s. Uplers does not list "
            "them; that is not changed here and is not this server's call."
            % (len(kept), ", ".join(kept[:12]))
        )
    if removed:
        notes.append(
            "replace_skills=True DISCARDED %d local-only skill(s): %s. The backup has them."
            % (len(removed), ", ".join(removed[:12]))
        )

    result = ProfileSyncResult(
        applied=False,
        skills_before=len(current),
        skills_after=len(merged),
        skills_added=added,
        skills_removed=removed,
        local_only_kept=kept,
        fields_changed=changes,
        left_for_you=left_for_you,
        notes=notes,
    )

    if not confirm:
        result.notes.insert(
            0,
            "PREVIEW - nothing was written. Re-run with confirm=True to apply. Only "
            "the local data/profile.json changes; your Uplers profile is never touched.",
        )
        return result

    # Snapshot BEFORE the write, so the operator can always get back.
    target = prof.profile_path()
    backup = None
    if target.is_file():
        backup = target.with_name(
            "profile.backup-%s.json" % ids.utcnow_iso().replace(":", "").replace("-", "")[:15]
        )
        backup.write_bytes(target.read_bytes())

    prof.save(local.model_copy(update=updates), path=target)

    result.applied = True
    # Relativised like every other path here, which for a while looked like it
    # would break this one: `backup_path` is the UNDO HANDLE for a destructive
    # sync and the caller is expected to OPEN it. It is not a trade - the handle
    # is rendered here and anchored again by profile.resolve_backup_handle(),
    # which accepts the absolute form too so a handle from an older run still
    # works. Leak closed, undo intact.
    result.backup_path = policy_mod.display_path(str(backup)) if backup else None
    result.notes.append(
        "Local profile updated. Fit scores computed before now were against the old "
        "%d-skill set; re-run uplers_rank_opportunities() to see the corrected ones."
        % len(current)
    )
    return result


@mcp.tool()
async def uplers_my_interviews(detailed: bool = True) -> InterviewList:
    """Interviews Uplers has arranged for you.

    Read-only. Args:
        detailed: ask Uplers for the fuller record.
    """
    params = {"detailed": "true"} if detailed else None
    async with _talent_client() as client:
        payload = await client.get_json(endpoints.EP_INTERVIEW_LIST, params)
    interviews, notes = talent_shape.interviews_from(payload)
    return InterviewList(interviews=interviews, count=len(interviews), notes=notes)


@mcp.tool()
async def uplers_my_assessments() -> MyAssessments:
    """Assessments YOU have sat, and whether Uplers counts them cleared.

    The other half of a story this server only told from one side. Every
    requisition already reports what it DEMANDS - `uplers_get_opportunity()`
    lists them and `uplers_assess_fit()` raises a flag - but nothing reported
    what you have already DONE, so a required assessment always read as an
    obstacle even when it was an afternoon already spent.

    It is worth asking on this board specifically: 99 of the 250 indexed
    requisitions carry a non-empty assessments array, so roughly 40% of the
    reachable work is gated behind an AiInterview or a TestGorilla test.

    Read-only, no arguments. Sitting an assessment is done on Uplers' own site;
    this server does not start one, and deliberately does not - `assign-assessment`
    opens a third-party testing tool in a browser and is not a thing to trigger
    from a tool call.
    """
    async with _talent_client() as client:
        payload = await client.get_json(endpoints.EP_ASSESSMENTS, None)
    return talent_shape.my_assessments_from(payload)


@mcp.tool()
async def uplers_agent_readthrough() -> dict:
    """What Uplers' OWN autonomous agent has done for you, and what it missed.

    You are PAYING for that agent - plan 2, `outreach_mode: "auto"`, auto-run
    on - and until now this server could not see a thing it did. This reads
    its output. It does not run it, queue it, or apply to anything: five plain
    GETs, and no write path anywhere in this tool or the module behind it.

    Reading an agent you already own is not the same as building a second one,
    and this server deliberately does NOT build one. A second uncoordinated
    applier on one account, against a 250-requisition board where expressing
    interest CANNOT BE UNDONE, is the wrong answer regardless of how good the
    applier is.

    WHAT TO LOOK AT FIRST. `needs_reply` is the whole reason this exists:
    positive replies came back from real people at real companies and are
    sitting unanswered, ranked oldest-first with how many days each has
    waited. `channels` is the second: the agent has two channels and one of
    them was never connected, and Uplers' own failure text on the failed runs
    names it. `cross_checks` and `disagreements` are the honesty layer - where
    two of Uplers' own routes report different numbers, both are shown rather
    than one being quietly picked.

    Contact details ARE withheld on purpose. The reply category, the company,
    the role and the thread id are enough to act on; the counterparty's email
    address and the verbatim body of their message do not need to be printed
    into a transcript to answer them. Open the thread.

    Read-only, no arguments. Costs six requests.
    """
    async with _talent_client() as client:
        plan_raw = await client.get_json(endpoints.EP_OUTREACH_STEP, None)
        dashboard_raw = await client.get_json(endpoints.EP_OUTREACH_DASHBOARD, None)
        pending_raw = await client.get_json(endpoints.EP_OUTREACH_PENDING, None)
        missed_raw = await client.get_json(endpoints.EP_OUTREACH_MISSED_FOLLOWUPS, None)
        activity_raw = await client.get_json(endpoints.EP_OUTREACH_ACTIVITY, None)
        meta_raw = await client.get_json(endpoints.EP_OUTREACH_AGENT_META, None)

    now = datetime.now().astimezone()
    return outreach_mod.agent_readthrough(
        plan=outreach_mod.shape_agent_plan(plan_raw, today=now.date().isoformat()),
        dashboard=outreach_mod.shape_agent_dashboard(dashboard_raw),
        pending=outreach_mod.shape_pending_jobs(pending_raw),
        missed=outreach_mod.shape_missed_followups(missed_raw, now=now.isoformat()),
        activity=outreach_mod.shape_activity(activity_raw),
        agent_meta=outreach_mod.shape_agent_meta(meta_raw),
    )


@mcp.tool()
async def uplers_email_scan() -> dict:
    """Whether Uplers is scanning your Gmail for jobs, and what it found.

    THE AUTHORITATIVE ANSWER, which this server did not have until now. Uplers
    reports something called a mailbox-scan consent on three different routes
    and they do not agree, so "is the scan on" had no single answer here. It
    does now: `has_consent` on `recommended-jobs-meta-email` is the platform's
    own state, established by static analysis of Uplers' frontend bundle
    (`_audit/_slices/_slice-consent-semantics.md`) - this is the route their UI
    re-reads the instant the consent write lands, and the whole Recommended-jobs
    screen switches on it. `get-outreach-dashboard-data -> consent_email_job_scan`
    is a downstream copy of the same fact, and `interview-list -> meta.has_consent`
    is a DIFFERENT consent entirely - the interview scan, whose UI Uplers designed
    and never shipped - despite carrying the identical field name.

    TWO THINGS THIS TOOL WILL NOT DO, both of them measured rather than assumed:

    It does not flatten the grant TIME into a yes/no. `consent_email_job_scan`
    on this route is a timestamp string, not the boolean the dashboard sends
    under the same key, and it is reported as `consent_granted_at` - the only
    record the account holds of when the scan was switched on.

    It does not pick a winner between Uplers' own two counters.
    `best_for_you_count` and the sum of `best_for_you_breakdown` disagree by one
    on the captured payload. Both are reported and `counters_agree` says
    plainly that they do not. Averaging them would invent a third number nobody
    sent.

    The mailbox ADDRESS is in the payload and is deliberately not returned;
    whether a mailbox is connected is the fact worth having, and the address
    would only ever be printed into a transcript.

    Read-only, no arguments, one request. This tool reads the consent; it
    cannot grant or revoke one. `consent-email-job-scan` is a POST/DELETE
    sibling one path segment away and is not built anywhere in this server.
    """
    async with _talent_client() as client:
        payload = await client.get_json(endpoints.EP_OUTREACH_META_EMAIL, None)
    return agent_surface.shape_email_scan(payload)


@mcp.tool()
async def uplers_scanned_jobs(
    best_for_you: bool | None = None, limit: int = 25
) -> dict:
    """The jobs Uplers' Gmail scan actually found, listed.

    `uplers_email_scan()` says the scan ran and holds 79 jobs; this is the list
    itself, and no tool in this server could reach it. Every captured row came
    off LinkedIn job alerts sitting in his mailbox, which is why the rows look
    the way they do.

    NO FIT SCORE IS COMPUTED FOR THESE ROWS, and that is a promise being kept
    rather than a feature missing. Fit scores in this server come from jobcore
    and mean the same thing as they do on the Naukri server. MEASURED across
    all 79 captured rows: `skills` is the empty list on every one, `city` is
    empty on every one, and `description` is the same placeholder telling you
    to open the link. Scoring that would produce a number with nothing behind
    it - and nothing on the surface of a number says which kind it is, which is
    exactly how a shared scale stops meaning anything. Open the `apply_url`, or
    score the same role off the Uplers board where the requisition has real
    fields. The row counts this rests on are re-derived on every call and
    reported in `scoring`, so a route that starts sending real fields will say
    so itself.

    `limit` TRUNCATES THIS TOOL'S OUTPUT, NOT THE REQUEST. The route has no
    working limit of its own - a `limit=3` against its sibling
    `get-recommended-jobs` returned all 97 rows - so the full list arrives and
    is counted either way, and `total_rows` always reports the real size.
    Raising `limit` costs no extra request.

    Read-only, one request.

    Args:
        best_for_you: unset fetches the whole list (79 rows measured);
            True fetches Uplers' "best for you" subset (51 measured). False is
            REFUSED rather than sent, because it was never measured on this
            route - fetch the whole list, which carries the 28 non-best rows
            too, and filter them where you can see the filtering happen.
        limit: how many rows to return. Truncates output only.
    """
    params = agent_surface.scanned_jobs_params(best_for_you)
    async with _talent_client() as client:
        payload = await client.get_json(endpoints.EP_OUTREACH_SCANNED_JOBS, params)
    result = agent_surface.shape_scanned_jobs(payload, limit=limit)
    result["best_for_you_filter"] = best_for_you
    return result


@mcp.tool()
async def uplers_agent_settings() -> dict:
    """The four switches that decide what your paid agent actually does.

    `uplers_agent_readthrough()` reports what the agent DID. This reports the
    machinery deciding what it does next, and the point of reading it is that
    every one of these can be off without leaving a mark in the activity log:

    FOLLOW-UP, per channel, with its interval. Uplers stores this INVERTED as
    `disabled_followup_<channel>`, so a reader that passed the field through
    unchanged would report every live channel as dead and every dead one as
    live. The negation is done once, in the shaper, and each channel carries
    the raw field name so the two can be checked against each other.

    TEMPLATES, per channel: whether one exists and what its subject line says.
    THE BODY IS NEVER RETURNED, on any channel. The gmail template is a
    multi-paragraph self-description carrying employer history, a LinkedIn URL
    and a notice period; the fact that it exists and the subject it sends under
    are what a reader needs, and the rest does not belong in a transcript. The
    linkedin template measured as the EMPTY STRING, which corroborates from a
    second route what `outreach-step` already said with `linkedin_connected:
    false` - that channel is dead at both ends.

    AUTO-REPLY: whether it handles replies at all, the delay in hours, and the
    categories it would answer. It is OFF, and one of its eight categories is
    `asking_resume`, which is the category his oldest unanswered reply falls
    into. That is stated as a fact about the account and carries no
    recommendation - whether software should answer somebody who asked him for
    his resume is his call.

    BLOCKED COMPANIES: the real blocklist, and what Uplers means when an agent
    run fails with "You blocked this company for outreach". It is NOT
    `settings/companies`, which is an alphabetical company picker paginated at
    20 rows; reading a blocklist off that route would report the first twenty
    companies in the alphabet as blocked.

    Read-only, no arguments, four requests. Nothing here writes and no write
    route in this namespace is reachable from this tool. Two of them are built
    elsewhere and are named rather than left implied: uplers_revoke_email_scan
    (the consent DELETE) and uplers_submit_interview_feedback (ONE-WAY).
    `consent-auto-run` and the GRANT arm of the consent are not built at all.
    """
    async with _talent_client() as client:
        followup_raw = await client.get_json(
            endpoints.EP_OUTREACH_SETTINGS_FOLLOWUP, None
        )
        blocked_raw = await client.get_json(
            endpoints.EP_OUTREACH_DISABLED_COMPANIES, None
        )
        auto_reply_raw = await client.get_json(endpoints.EP_OUTREACH_AUTO_REPLY, None)
        templates_raw = await client.get_json(endpoints.EP_OUTREACH_TEMPLATES, None)

    return agent_surface.agent_settings(
        followup=agent_surface.shape_followup_settings(followup_raw),
        templates=agent_surface.shape_templates(templates_raw),
        auto_reply=agent_surface.shape_auto_reply(auto_reply_raw),
        blocked=agent_surface.shape_disabled_companies(blocked_raw),
    )


# --------------------------------------------------------------- tool 59 ---
#
# THE PAID CANDIDATE SKUs, READ ONLY. Read `uplers_server/skus.py` before
# touching either tool below; both wrappers here are deliberately thin and
# every decision lives in that module.
#
# These two exist because a standing refusal was NARROWED by measurement.
# `out_of_scope_by_design` refused `talent/resume-health-check/*` and
# `talent/tailor/*` outright, partly on the concrete ground that wrapping them
# "would produce tools that fail at runtime" for want of credits. MEASURED
# 2026-08-25 on his live session: all three read routes answered HTTP 200 with
# real data, zero 403s and zero 402s. The credit gate is on the WRITE side.
# Every ordering, transforming and refunding route in both namespaces stays
# refused and stays nameless in endpoints.py.


@mcp.tool()
async def uplers_resume_health() -> dict:
    """Your Uplers resume health check: the score, the verdict, and the history.

    Uplers splits this across two routes - one for the CURRENT state and one
    for the HISTORY - and this reads both, because they answer the same
    question from opposite sides and a caller should not have to know that.

    IT IS ALSO WHAT MAKES ONE NUMBER READABLE. The current route sends two bare
    counters, `user_attempts` and `total_attempts`, and nothing on it says
    which is spent and which is the cap. The history route independently
    reports its own count AND returns its own rows, and all three read 3 - so
    `user_attempts` is identifiable as the spent one by corroboration rather
    than by its name. That cross-check is computed and shipped in the result;
    if the routes ever stop agreeing the report says so instead of picking one.

    MEASURED 2026-08-25: he scored **89**, he has run 3 checks of 5, and
    `is_eligible` reads FALSE anyway. Those last two are printed side by side
    and NOT reconciled - 5 minus 3 leaves 2, the account says no more are
    offered, and this server does not know which governs. `is_paid: false` is a
    candidate explanation and is labelled a hypothesis, not a measurement.

    THERE IS NO VERDICT TEXT. `final_verdict` is present on every row and is
    the EMPTY STRING on all four of them, so the result distinguishes "Uplers
    shipped no verdict" from "this server could not read one" rather than
    collapsing both onto null.

    NOT RETURNED, ON PURPOSE: the `report_details` body. It is Uplers' scoring
    report on your resume - it carries your name, states your city, and quotes
    whole resume bullets back verbatim - and it does not belong in a
    transcript, the same rule `uplers_agent_settings` applies to your outreach
    template bodies. Filenames and the `aws_file_name` go with it, and so does
    every link to the document, which is treated as a bearer credential. The
    cost is stated in the result under `unsurfaced`: the per-check breakdown,
    including the one measured red flag, is dropped with its container.

    Read-only, no arguments, two requests. Nothing here orders, buys,
    transforms or refunds anything.
    """
    async with _talent_client() as client:
        last_raw = await client.get_json(endpoints.EP_SKU_HEALTH_CHECK_LAST, None)
        dashboard_raw = await client.get_json(
            endpoints.EP_SKU_HEALTH_CHECK_DASHBOARD, None
        )

    return skus.resume_health(
        last=skus.shape_last_health_check(last_raw),
        dashboard=skus.shape_health_check_dashboard(dashboard_raw),
    )


@mcp.tool()
async def uplers_tailored_resumes() -> dict:
    """Tailored resumes that already exist, and the state of your tailor plan.

    NOT `uplers_tailored_jobs`, which is a different surface with a
    confusingly similar name: that one asks Uplers which REQUISITIONS suit you.
    This one reads what the paid resume TAILOR has actually produced.

    THE TRAP ON THIS ROUTE IS ITS ROW COUNT, and it is why this tool is worth
    having rather than reading the raw payload. MEASURED 2026-08-25:
    `total_records` reads 1 while `total_tailored_resumes` reads 0. The single
    row is a SOURCE row - a base resume registered as tailoring INPUT, with
    `tailored_resume: null` - so anything that treated the row count as the
    tailored count would report a tailored resume that does not exist. The two
    counts are kept apart by name here, and each row is classified from its own
    fields rather than from being in the list. The answer today is that NO
    tailored resume exists, from two independent readings of one payload.

    THE PLAN IS INACTIVE, by three fields agreeing: `plan_active` 0,
    `remaining_days` 0, and a `plan_end_date` of 2026-08-11. The date is passed
    through and never compared to today - this server's shapers have no clock,
    so that a fixture pins them.

    `plan_type` reads 4 and `status` reads 2. Both are UNLABELLED integers and
    no meaning is attached to either; in particular `plan_type` is NOT an index
    into `talent/outreach/agent-plans`, which catalogues only ids 1 and 3.

    Filenames are withheld, on the same rule as uplers_resume_health.

    Read-only, no arguments, one request. talent/tailor/order/create,
    order/capture and refund-request are refused and have no constant in this
    server, so nothing here can buy, order or refund anything.
    """
    async with _talent_client() as client:
        payload = await client.get_json(endpoints.EP_SKU_TAILOR_LIST, None)

    return skus.shape_tailor_list(payload)


# --------------------------------------------------------------- tool 51 ---
#
# The resume write. Read `uplers_server/resume_write.py` before touching any of
# the three tools below. Uplers keeps NO previous copy of a resume - VERIFIED
# absences across their whole production bundle, and their download route takes
# no "which resume" parameter - so the pre-flight snapshot is not a convenience,
# it is the entire rollback story. Everything in that module is a guard around
# taking it BEFORE the write, or around the restore being turned into a delete.


@mcp.tool()
async def uplers_replace_resume(file_path: str, confirm: bool = False) -> dict:
    """Replace the resume Uplers recruiters see. Previews by default.

    This changes who you are on Uplers rather than acting on a job, and it is
    the only write here that acts on a FILE. Whether it SHOULD run is not this
    server's call.

    READ THIS BEFORE CONFIRMING. Uplers keeps no previous copy: no history, no
    version list, no archive, and no revert route anywhere in their product.
    The only rollback that exists is the snapshot this tool takes BEFORE the
    write - their own download route has no "which resume" parameter, so once
    the replacement lands it returns the new file and the old one is
    unreachable. If the snapshot cannot be taken, or cannot be written to disk,
    or comes back in a form that cannot be re-uploaded, THE WRITE DOES NOT
    HAPPEN. That is a precondition, not a warning.

    The snapshot restores the FILE, not the RECORD. Anything Uplers derived
    from the old resume - parsed profile fields, a health score, a tailored
    variant - is not put back by re-uploading bytes.

    And the blast radius is UNRESOLVED. The bundle names a profile-completion
    recompute and nothing else, but whether Uplers re-parses, re-scores,
    notifies a recruiter or touches already-submitted applications could not be
    determined from a client bundle, and absence of evidence there is not
    evidence of absence on their server. Do not read this write as contained.

    With confirm=False it returns the exact request it would send, tells you
    whether a restore point can be taken, and changes nothing.

    Args:
        file_path: the new resume. pdf or docx, 2 MB maximum - Uplers' own
            gate, mirrored to the byte.
        confirm: False previews. True snapshots, then sends.
    """
    async with _talent_client() as client:
        return await resume_write.replace_resume(
            client,
            file_path,
            confirm=confirm,
            send=resume_write.sender_for(client, endpoints.EP_PROFILE_UPSERT),
        )


@mcp.tool()
async def uplers_restore_resume(
    snapshot_id: str | None = None, confirm: bool = False
) -> dict:
    """Put a snapshotted resume back on your profile. Previews by default.

    Snapshots are written automatically before every uplers_replace_resume()
    write. This uploads one of them again.

    It is a fresh upload through the same replacement route, not a revert, so
    it is exactly as destructive as the thing it undoes: whatever is on the
    profile now is replaced by what the snapshot holds. That state is itself
    snapshotted first. Preview before confirming.

    Args:
        snapshot_id: which restore point. Omit for the most recent.
        confirm: False previews. True sends the write.
    """
    async with _talent_client() as client:
        return await resume_write.restore_resume(
            client,
            snapshot_id,
            confirm=confirm,
            send=resume_write.sender_for(client, endpoints.EP_PROFILE_UPSERT),
        )


@mcp.tool()
async def uplers_list_resume_snapshots() -> dict:
    """Resume restore points, newest first. Reads disk only, needs no session.

    One is written before every uplers_replace_resume() write and one before
    every restore. Each entry names the file, its size and its sha256, and says
    whether it can be re-uploaded. An empty list means this server has never
    replaced your Uplers resume.
    """
    entries = resume_write.list_snapshots()
    return {
        "snapshots": entries,
        "directory": policy_mod.display_path(str(resume_write.snapshots_dir())),
        "notes": (
            []
            if entries
            else [
                "No resume snapshots. This server has never replaced your Uplers "
                "resume."
            ]
        ),
    }


@mcp.tool()
async def uplers_platform_saved_jobs(
    search: str | None = None, page: int = 1, page_size: int = 20
) -> dict:
    """Jobs YOU bookmarked on Uplers' own site. Not this server's shortlist.

    There are two saved lists and they have never been the same list.
    `uplers_save_job()` writes a LOCAL shortlist in this server's database;
    this reads the bookmarks Uplers holds, the ones the star on their own
    board creates. Neither can see the other, so reading both is the only way
    to know what is actually on your list.

    ONE FILTER AND NO OTHERS, and that is a real trap rather than a
    limitation. Uplers' own code short-circuits every other filter when the
    saved flag is set - `roles`, `locations`, `experience` and `engagements`
    are all DROPPED - so a filtered request comes back as your saved jobs
    UNFILTERED while looking filtered. `search` is the single exception. Ask
    for anything else and this refuses rather than sending it; filter the
    result here instead.

    Args:
        search: free-text, the only filter this view honours.
        page: 1-based page.
        page_size: rows per page.
    """
    params = saved_filter.saved_jobs_params(
        search=search, page=page, pagination=page_size
    )
    saved_filter.assert_integer_one(params)
    async with _talent_client() as client:
        payload = await client.get_json(endpoints.EP_OPPORTUNITIES, params)
    result = saved_filter.read_saved_page(payload)
    result["source"] = endpoints.EP_OPPORTUNITIES
    return result


@mcp.tool()
async def uplers_my_preferences() -> dict:
    """What UPLERS thinks you want - which is not what this server thinks.

    Every fit score here is computed against the local profile
    (`uplers_my_profile()`). Uplers ranks you against THESE, and the two have
    never been compared because one of them was invisible. Where they part
    company is where your feed stops making sense.

    Ids are resolved to labels against the lookup tables Uplers ships in the
    same response. An id with no matching row comes back marked UNRESOLVED
    rather than dropped or guessed at, and `unresolved` lists them, because a
    preference silently rendered as nothing reads as a preference you do not
    have.

    Read-only, no arguments. Changing any of this is done on Uplers' own site:
    the write route is a DIFFERENT endpoint that alters how recruiters see
    you, and this server does not call it.
    """
    async with _talent_client() as client:
        payload = await client.get_json(endpoints.EP_GET_PREFERENCE, None)
    shaped = preference_mod.shape_preference(payload)
    shaped["source"] = endpoints.EP_GET_PREFERENCE
    return shaped


@mcp.tool()
async def uplers_assessment_gates(page_size: int = 50) -> dict:
    """Which jobs in your feed demand an assessment BEFORE you can apply.

    No new endpoint: `ai_needed` and `custom_screening_needed` already ride on
    the feed rows this server reads, and were simply never surfaced.

    READ THE CAVEAT. These are PRE-APPLY signal - "this requisition will want
    a test first" - and they are NOT pipeline signal. All 9 of your existing
    applications read `ai_needed: false`, so nothing here explains why they
    stall. What it does tell you is which rows cost an assessment to enter.

    For context this tool cannot derive from one page: 99 of the 250 indexed
    requisitions carry a non-empty assessments array, and
    `uplers_my_assessments()` reports 0 cleared. Absent is reported as
    `unknown` and never folded into `false` - a row that never carried the
    field is not a row that said no.

    Args:
        page_size: feed rows to read in one request.
    """
    params = _feed_params(
        page=1,
        page_size=page_size,
        sort="relevance",
        experience=None,
        roles=None,
        locations=None,
        modes=None,
    )
    async with _talent_client() as client:
        payload = await client.get_json(endpoints.EP_OPPORTUNITIES, params)

    rows = []
    if isinstance(payload, dict) and isinstance(payload.get("hrs"), dict):
        rows = payload["hrs"].get("data") or []
    summary = assessment_flags.summarise_flags(rows)
    summary["source"] = endpoints.EP_OPPORTUNITIES
    summary["scope"] = (
        "one feed page of %d row(s). Not the whole 250-requisition board."
        % len(rows)
    )
    return summary


@mcp.tool()
async def uplers_filter_options(kind: str, search: str | None = None, limit: int = 40) -> dict:
    """The id lists uplers_my_feed() filters need. Ids, not names.

    uplers_my_feed(roles=..., locations=...) takes Uplers' internal ids, so
    this is how you turn "React" or "Bangalore" into something the feed
    accepts.

    Args:
        kind: "role", "skill", "location" or "company".
        search: filter the list server-side. Recommended - these are long.
        limit: cap on returned entries.
    """
    routes = {
        "role": endpoints.EP_ROLE_MASTER,
        "skill": endpoints.EP_SKILL_MASTER,
        "location": endpoints.EP_LOCATION_MASTER,
        "company": endpoints.EP_COMPANY_MASTER,
    }
    if kind not in routes:
        raise UplersError("kind must be one of %s (got %r)." % (sorted(routes), kind))

    params: dict = {}
    if search:
        params["search"] = search
    if kind == "company":
        params["company_type"] = endpoints.DEFAULT_COMPANY_TYPE

    async with _talent_client() as client:
        payload = await client.get_json(routes[kind], params or None)

    if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
        raise TalentError(
            "%s returned no `data` array (keys: %s), so no options could be read."
            % (
                routes[kind],
                sorted(payload)[:12] if isinstance(payload, dict) else type(payload).__name__,
            )
        )
    rows = payload["data"][:limit]
    options = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        # Every master route names the id `value`; none of them sends `id`.
        # Reading `id` first made every option id None, and the drop-nothing
        # filter below then emptied the list on all four kinds.
        identifier = talent_shape._first(row, "value", "id")
        if identifier is None:
            continue
        options.append(
            {
                "id": identifier,
                "name": talent_shape._stringify(
                    talent_shape._first(row, "label", "name", "title", "city")
                ),
            }
        )
    return {
        "kind": kind,
        # `returned` counts what SHIPPED. Counting the pre-filter list is how
        # `options: []` sat next to `returned: 5` without anyone noticing.
        "options": options,
        "returned": len(options),
        "total_available": len(payload["data"]),
        "search": search,
    }


# -------------------------------------------------------------- writes ----
#
# Two writes exist here and they are NOT the same kind of act.
#
#   uplers_apply    - PERMANENT. There is no undo anywhere in Uplers' product.
#   uplers_dismiss  - reversible, by design, with an explicit reset flag.
#
# A third route, `talent/hr/cancel-opportunity`, is deliberately NOT exposed.
# Its name suggests "withdraw an application" and it is not that: it declines a
# job you have NOT applied to, and in the shipped build its only call site sits
# behind a condition (`opportunityType === "matched"`) that nothing in 13.4 MB
# of their bundle ever satisfies. Exposing it as a withdraw would be the most
# dangerous kind of wrong - it would imply an undo that does not exist.


async def _resolve_for_write(client: TalentClient, hr_number: str) -> dict:
    """Fetch the authenticated record so a write names a real job with a real id.

    Every write below goes through this first. It costs one request and buys
    three things: proof the requisition exists, the numeric `id` the write
    actually needs (the public tier never sees it), and the current state - so
    an apply that has already happened is caught before it is repeated.
    """
    payload = await client.get_json(endpoints.EP_SINGLE_HR, {"hr_number": hr_number})
    if not isinstance(payload, dict) or not payload:
        raise TalentError(
            "%s returned nothing for %s, so there is no job to act on."
            % (endpoints.EP_SINGLE_HR, hr_number)
        )
    return payload


@mcp.tool()
async def uplers_apply(hr_number: str, confirm: bool = False) -> WritePreview | WriteResult:
    """Express interest in a requisition. THIS IS AN APPLICATION AND IT CANNOT BE UNDONE.

    On Uplers, "express interest" IS applying - their own analytics call this
    button Apply, and once it is done the button goes disabled and reads
    "Applied". There is **no withdraw, no cancel, no un-apply anywhere in
    their product**: the only path that retracts applications is deactivating
    your entire account. Treat every call as final.

    Nothing is sent unless `confirm=True`. With `confirm=False` this returns a
    preview of the exact request it would make, and performs nothing.

    This also refuses to apply twice: if Uplers already has you down as
    interested, it says so instead of sending a duplicate.

    Args:
        hr_number: the requisition, e.g. "HR130826031902".
        confirm: must be True to actually send it. There is no undo.
    """
    hr_number = _validate_hr(hr_number)
    async with _talent_client() as client:
        record = await _resolve_for_write(client, hr_number)
        row = talent_shape.to_talent_row(record)

        if row.job_id is None:
            raise TalentError(
                "Uplers' record for %s carries no numeric `id`, which is the field "
                "the apply route needs. Refusing to guess one." % hr_number
            )
        if row.applied is True:
            return WriteResult(
                action="apply",
                hr_number=hr_number,
                title=row.title,
                company=row.company,
                performed=False,
                reversible=False,
                notes=[
                    "Uplers already has you down as interested in this requisition, "
                    "so nothing was sent. Applying twice is not possible and not useful."
                ],
            )

        body = {"hr_id": row.job_id, "intrested": 1}
        warning = (
            "PERMANENT. Uplers has no withdraw, cancel or un-apply for an expressed "
            "interest - the only thing that retracts applications is deactivating "
            "your whole account."
        )
        if not confirm:
            return WritePreview(
                action="apply",
                hr_number=hr_number,
                title=row.title,
                company=row.company,
                method="POST multipart/form-data",
                endpoint=endpoints.EP_INTRESTED,
                body=body,
                reversible=False,
                performed=False,
                warning=warning,
                to_confirm='uplers_apply("%s", confirm=True)' % hr_number,
            )

        response = await client.post_form(endpoints.EP_INTRESTED, body)

    return WriteResult(
        action="apply",
        hr_number=hr_number,
        title=row.title,
        company=row.company,
        performed=True,
        reversible=False,
        response=response if isinstance(response, dict) else {},
        notes=[
            warning,
            "Track it with uplers_my_pipeline() - that reads Uplers' own status, "
            "which is authoritative.",
        ],
    )


@mcp.tool()
async def uplers_dismiss(
    hr_number: str,
    confirm: bool = False,
    undo: bool = False,
    reason_ids: list[int] | None = None,
) -> WritePreview | WriteResult:
    """Mark a requisition "not interested", or undo that. Reversible either way.

    Unlike uplers_apply, this one is genuinely reversible: Uplers' own UI has
    an explicit reset for it, so a mistake here costs nothing. Dismissing hides
    the job from your feed; `undo=True` puts it back.

    Nothing is sent unless `confirm=True`.

    Args:
        hr_number: the requisition.
        confirm: must be True to actually send it.
        undo: reverse a previous dismissal instead of creating one.
        reason_ids: Uplers' own reason codes, when you want to give a reason.
    """
    hr_number = _validate_hr(hr_number)
    action = "undismiss" if undo else "dismiss"
    body: dict = (
        {"hr_number": hr_number, "reset_not_interested": True}
        if undo
        else {"hr_number": hr_number, "reason_ids": list(reason_ids or [])}
    )

    async with _talent_client() as client:
        record = await _resolve_for_write(client, hr_number)
        row = talent_shape.to_talent_row(record)

        if not confirm:
            return WritePreview(
                action=action,
                hr_number=hr_number,
                title=row.title,
                company=row.company,
                method="POST application/json",
                endpoint=endpoints.EP_NOT_INTERESTED,
                body=body,
                reversible=True,
                performed=False,
                warning=None,
                to_confirm='uplers_dismiss("%s", confirm=True%s)'
                % (hr_number, ", undo=True" if undo else ""),
            )

        response = await client.post_json(endpoints.EP_NOT_INTERESTED, body)

    return WriteResult(
        action=action,
        hr_number=hr_number,
        title=row.title,
        company=row.company,
        performed=True,
        reversible=True,
        reverse_with='uplers_dismiss("%s", confirm=True%s)'
        % (hr_number, "" if undo else ", undo=True"),
        response=response if isinstance(response, dict) else {},
    )


# --------------------------------------------------------------- tool 37 ---
#
# The profile write. Read `uplers_server/profile_write.py` before touching any
# of the three tools below - the route is REPLACEMENT semantics and the failure
# mode is silent deletion of things a person typed in by hand.


def _stamp_to_iso(stamp) -> str | None:
    """Snapshot timestamps are unix floats on disk; a reader wants a date."""
    if stamp is None:
        return None
    try:
        return datetime.fromtimestamp(float(stamp), timezone.utc).isoformat(
            timespec="seconds"
        )
    except (OSError, OverflowError, ValueError):
        return None


def _replacement_warning(value: list[dict]) -> str:
    return (
        "REPLACEMENT WRITE. Uplers replaces your ENTIRE skill list with the %d rows in "
        "`value`; anything not in this list is DELETED. There is no skills delete route "
        "on Uplers and no undo - removal happens by omission. The snapshot is the only "
        "way back." % len(value)
    )


@mcp.tool()
async def uplers_update_profile(
    add_skills: list[str] | None = None,
    remove_skills: list[str] | None = None,
    confirm: bool = False,
) -> ProfileWriteResult:
    """Change the skills on your REAL Uplers profile. Previews by default.

    This is the only tool here that changes who you are rather than acting on
    a job. Whether it SHOULD run is not this server's call - it does not know
    what you agreed with whom, or why a skill is or is not on your profile.

    READ THIS BEFORE CONFIRMING. Uplers' skills endpoint is a REPLACEMENT: it
    overwrites your whole list with what is sent, and a skill left out is
    deleted. There is no delete route and no undo. This tool therefore reads
    your live profile, applies your change to the complete set, and sends all
    of it - and it writes a snapshot first, which is the only way back.

    With confirm=False it returns the exact request it would send and changes
    nothing. Read the `value` array in `request_body`: that array IS the
    decision.

    Args:
        add_skills: skills to add. Matched case-insensitively against your
            existing ones and against Uplers' master list, so a known skill
            keeps its real id and its own spelling.
        remove_skills: skills to remove. Removal is by omission from the array.
        confirm: False previews. True sends the write.
    """
    async with _talent_client() as client:
        payload = await client.get_json(endpoints.EP_PROFILE)

    plan = profile_write.plan_skills(
        payload, add=add_skills or [], remove=remove_skills or []
    )
    body = profile_write.request_body(plan["value"])
    before = len(profile_write.current_skill_rows(payload))

    notes = [_replacement_warning(plan["value"])]
    if plan["unknown_removals"]:
        notes.append(
            "Not on your profile, so nothing to remove: %s."
            % ", ".join(plan["unknown_removals"])
        )

    result = ProfileWriteResult(
        applied=False,
        request_method="POST",
        request_path=endpoints.EP_PROFILE_UPSERT,
        request_body=body,
        skills_before=before,
        skills_after=len(plan["value"]),
        skills_added=plan["added"],
        skills_removed=plan["removed"],
        notes=notes,
    )

    if not confirm:
        result.notes.insert(
            0,
            "PREVIEW - nothing was sent. Check the `value` array, then re-run with "
            "confirm=True.",
        )
        return result

    # Snapshot BEFORE the request, never after: a snapshot taken after a write
    # that half-succeeded records the damage rather than the way back.
    snapshot = profile_write.write_snapshot(payload, label="pre-skills-write")
    result.snapshot_id = snapshot["snapshot_id"]

    async with _talent_client() as client:
        await client.post_json(endpoints.EP_PROFILE_UPSERT, body)
        # Verified by re-reading, not by trusting a 200. This route replaces a
        # list; "the request succeeded" and "the list is what you wanted" are
        # different claims and only the second one matters.
        after = await client.get_json(endpoints.EP_PROFILE)

    landed = {row["label"].strip().lower() for row in profile_write.current_skill_rows(after)}
    wanted = {row["label"].strip().lower() for row in plan["value"]}
    result.applied = True
    result.verified = landed == wanted
    result.skills_after = len(landed)
    if not result.verified:
        result.notes.append(
            "WRITE LANDED BUT DID NOT VERIFY. Uplers now holds %d skills, not the %d "
            "sent. Missing: %s. Extra: %s. Restore with "
            "uplers_restore_profile(snapshot_id=%r, confirm=True)."
            % (
                len(landed),
                len(wanted),
                ", ".join(sorted(wanted - landed)[:10]) or "none",
                ", ".join(sorted(landed - wanted)[:10]) or "none",
                snapshot["snapshot_id"],
            )
        )
    else:
        result.notes.append(
            "Re-read after writing and the list matches. Restore point: %s."
            % snapshot["snapshot_id"]
        )
    return result


@mcp.tool()
async def uplers_restore_profile(
    snapshot_id: str | None = None, confirm: bool = False
) -> ProfileWriteResult:
    """Put your Uplers skills back to a snapshot. Previews by default.

    Snapshots are written automatically before every uplers_update_profile()
    write. This sends the snapshotted list back through the same replacement
    endpoint.

    A restore is itself a replacement write, so it is exactly as destructive as
    the thing it undoes: anything added since the snapshot is deleted by it.
    Preview first.

    Args:
        snapshot_id: which restore point. Omit for the most recent.
        confirm: False previews. True sends the write.
    """
    record = profile_write.load_snapshot(snapshot_id)
    body = profile_write.request_body(record["skills"])

    async with _talent_client() as client:
        payload = await client.get_json(endpoints.EP_PROFILE)
    current = profile_write.current_skill_rows(payload)

    live = {row["label"].strip().lower() for row in current}
    saved = {row["label"].strip().lower() for row in record["skills"]}

    result = ProfileWriteResult(
        applied=False,
        request_method="POST",
        request_path=endpoints.EP_PROFILE_UPSERT,
        request_body=body,
        skills_before=len(current),
        skills_after=len(record["skills"]),
        skills_added=sorted(
            row["label"] for row in record["skills"] if row["label"].strip().lower() not in live
        ),
        skills_removed=sorted(
            row["label"] for row in current if row["label"].strip().lower() not in saved
        ),
        snapshot_id=record.get("snapshot_id"),
        notes=[_replacement_warning(record["skills"])],
    )

    if not confirm:
        result.notes.insert(
            0,
            "PREVIEW - nothing was sent. This would restore snapshot %s, taken when you "
            "had %d skills." % (record.get("snapshot_id"), len(record["skills"])),
        )
        return result

    # The pre-restore state is itself worth keeping: a restore aimed at the
    # wrong snapshot is the obvious way to lose work, and without this there
    # would be nothing to come back to.
    profile_write.write_snapshot(payload, label="pre-restore")

    async with _talent_client() as client:
        await client.post_json(endpoints.EP_PROFILE_UPSERT, body)
        after = await client.get_json(endpoints.EP_PROFILE)

    landed = {row["label"].strip().lower() for row in profile_write.current_skill_rows(after)}
    result.applied = True
    result.verified = landed == saved
    result.skills_after = len(landed)
    return result


@mcp.tool()
async def uplers_list_profile_snapshots() -> SnapshotList:
    """Restore points for your Uplers profile, newest first. Reads disk only.

    One is written before every uplers_update_profile() write, and one before
    every restore. An empty list means this server has never written to your
    Uplers profile.
    """
    entries = profile_write.list_snapshots()
    return SnapshotList(
        snapshots=[
            SnapshotEntry(
                snapshot_id=entry["snapshot_id"],
                taken_at=_stamp_to_iso(entry.get("taken_at")),
                label=entry.get("label"),
                skills=entry.get("skills"),
            )
            for entry in entries
        ],
        directory=policy_mod.display_path(str(profile_write.snapshots_dir())),
        notes=(
            []
            if entries
            else ["No snapshots. This server has never written to your Uplers profile."]
        ),
    )


# --------------------------------------------------------------- tool 54 ---
#
# THE WRITE HALF OF THE FOUR SWITCHES `uplers_agent_settings` READS.
#
# Read `uplers_server/outreach_write.py` before touching any of the five tools
# below. Three things there are not obvious from here and each one is a live
# way to change the wrong thing with a 200 coming back:
#
#   * Uplers stores the follow-up flags INVERTED. `disabled_followup_gmail:
#     false` means gmail is ON. The negation happens once, in
#     outreach_write.to_disabled, and a second one anywhere cancels it.
#   * The blocklist DELETE takes the blocklist ROW id, not the company id.
#     Both are small integers on the same row.
#   * `provider` goes on the wire as an INTEGER: 1 LinkedIn, 2 Gmail.
#
# The wrappers are three lines each on purpose - the guards that run in
# production are the ones the tests exercise, not a copy of them.


@mcp.tool()
async def uplers_set_followup(
    gmail_enabled: bool | None = None,
    linkedin_enabled: bool | None = None,
    gmail_interval_days: int | None = None,
    linkedin_interval_days: int | None = None,
    gmail_message: str | None = None,
    linkedin_message: str | None = None,
    confirm: bool = False,
) -> dict:
    """Whether your paid agent chases an unanswered reply, and how often.

    This is the switch that decides whether somebody who replied and then heard
    nothing gets followed up at all. Reversible: Uplers serves this record on a
    GET at the same URL, so the exact prior values are read before the write
    and reported back to you.

    OMITTED ARGUMENTS ARE LEFT ALONE. Uplers' route takes the whole 9-key
    record every time, so this tool reads the live record first and carries
    over everything you did not name. A call that names nothing REFUSES rather
    than re-sending the record unchanged.

    The polarity here reads naturally and Uplers' does not - it stores these as
    `disabled_followup_*`, where false means the channel is on. Say
    `gmail_enabled=True` for "chase on gmail" and the inversion is handled.

    Uplers' own gate on the messages is mirrored: a follow-up message must
    contain both {{outreachEmployee}} and {{jobTitle}}, unless that channel is
    disabled or its message is empty. A message missing one is refused here
    rather than 422'd there.

    With confirm=False it returns the exact 9-key body it would send and
    changes nothing. Text you pass in is shown back verbatim; text carried over
    unchanged from Uplers renders as a length and a hash, because the body
    resends your existing follow-up messages on every write and an interval
    change should not print them into a transcript.

    Args:
        gmail_enabled: chase unanswered replies on gmail.
        linkedin_enabled: same for linkedin. NOTE that channel is not
            connected, so enabling it changes a setting and nothing else.
        gmail_interval_days: days between follow-ups. Clamped to at least 1,
            which is Uplers' own clamp.
        linkedin_interval_days: same for linkedin.
        gmail_message: the follow-up text. Must carry both template variables.
        linkedin_message: same for linkedin.
        confirm: False previews. True snapshots, then sends, then re-reads.
    """
    async with _talent_client() as client:
        return await outreach_write.set_followup(
            client,
            gmail_enabled=gmail_enabled,
            linkedin_enabled=linkedin_enabled,
            gmail_interval_days=gmail_interval_days,
            linkedin_interval_days=linkedin_interval_days,
            gmail_message=gmail_message,
            linkedin_message=linkedin_message,
            confirm=confirm,
            send=outreach_write.json_sender_for(
                client, endpoints.EP_OUTREACH_SETTINGS_FOLLOWUP
            ),
        )


@mcp.tool()
async def uplers_set_auto_reply(
    enabled: bool | None = None,
    hours: int | None = None,
    categories: list[str] | None = None,
    confirm: bool = False,
) -> dict:
    """Whether your agent answers replies for you, after how long, and to what.

    It is currently OFF. One of its eight categories is `asking_resume`, which
    is the category the oldest unanswered reply on this account falls into.
    That is a fact about the account and not a recommendation - whether
    software should answer somebody who asked you for your resume is your call,
    which is why this tool previews and does not act.

    Reversible: `talent/outreach/get-auto-reply` serves the same record, so the
    prior values are read before the write and can be put straight back.

    Uplers' own gate is mirrored: enabling with an empty category list is
    refused. Categories outside the eight this account has seen are NOT
    rejected - Uplers may know more than this fixture does - but the preview
    names them, so a typo is visible before you confirm.

    With confirm=False it returns the exact three-key body and changes nothing.

    Args:
        enabled: whether the agent answers replies at all.
        hours: how long it waits first.
        categories: which reply categories it will answer.
        confirm: False previews. True snapshots, then sends, then re-reads.
    """
    async with _talent_client() as client:
        return await outreach_write.set_auto_reply(
            client,
            enabled=enabled,
            hours=hours,
            categories=categories,
            confirm=confirm,
            send=outreach_write.json_sender_for(
                client, endpoints.EP_OUTREACH_UPDATE_AUTO_REPLY
            ),
        )


@mcp.tool()
async def uplers_set_template(
    channel: str, template: str, subject: str | None = None, confirm: bool = False
) -> dict:
    """Rewrite the outreach message your agent sends, on one channel.

    One channel per call - Uplers' own editor saves them independently and this
    does the same, so writing the linkedin template does not require re-sending
    the gmail one.

    THERE IS NO DELETE-TEMPLATE ROUTE ON UPLERS. The snapshot this tool takes
    before it sends is the only way back to the previous text, and a blank
    template body is refused rather than sent: their editor will happily store
    an empty string, and with no delete route that is indistinguishable from a
    mistake.

    The existing template body is never printed back to you, on any channel -
    the gmail one is a multi-paragraph self-description carrying employer
    history and a notice period. What you pass IN is echoed in the preview,
    because showing the exact body is the point of previewing.

    Writing the linkedin template does NOT connect the linkedin channel. That
    account is not linked, and linking it is not something this server can do -
    see uplers_server_info's out_of_scope_by_design.

    Args:
        channel: "gmail" or "linkedin". Goes on the wire as Uplers' integer.
        template: the message body.
        subject: the subject line.
        confirm: False previews. True snapshots, then sends, then re-reads.
    """
    async with _talent_client() as client:
        return await outreach_write.set_message_template(
            client,
            channel,
            template,
            subject,
            confirm=confirm,
            send=outreach_write.json_sender_for(
                client, endpoints.EP_OUTREACH_STORE_TEMPLATE
            ),
        )


@mcp.tool()
async def uplers_block_company(company_id: int, confirm: bool = False) -> dict:
    """Stop your agent from reaching out to one company. Genuinely reversible.

    This is the real blocklist - the one Uplers means when an agent run fails
    with "You blocked this company for outreach" - and not the alphabetical
    company picker a similarly-named route returns.

    The reverse is uplers_unblock_company, and it is a route Uplers ships
    rather than a workaround this server invented: their own UI names the pair.

    Blocking a company already on the list REFUSES rather than sending a write
    that would change nothing.

    Args:
        company_id: Uplers' company id. `uplers_agent_settings` lists the
            blocked set with their ids.
        confirm: False previews. True snapshots, then sends, then re-reads.
    """
    async with _talent_client() as client:
        return await outreach_write.block_company(
            client,
            company_id,
            confirm=confirm,
            send=outreach_write.json_sender_for(
                client, endpoints.EP_OUTREACH_DISABLED_COMPANIES
            ),
        )


@mcp.tool()
async def uplers_unblock_company(company_id: int, confirm: bool = False) -> dict:
    """Let your agent reach out to a company you had blocked. The reverse pair.

    Takes the COMPANY id, the same one uplers_block_company takes. Uplers'
    delete route wants a different number - the blocklist ROW id - and this
    tool resolves that from the live list rather than accepting it from you.
    Both numbers sit on the same row and both are small integers, so a caller
    passing one where the other belongs would remove a different company and
    get a 200 either way.

    Unblocking a company that is not on the list REFUSES rather than sending a
    delete for a row that is not there.

    Args:
        company_id: Uplers' company id, as uplers_agent_settings reports it.
        confirm: False previews. True snapshots, then sends, then re-reads.
    """
    async with _talent_client() as client:
        return await outreach_write.unblock_company(
            client,
            company_id,
            confirm=confirm,
            send=outreach_write.delete_sender_for(
                client, endpoints.EP_OUTREACH_DISABLED_COMPANY_DELETE
            ),
        )


# --------------------------------------------------------------- tool 61 ---
#
# THE TWO WRITES THAT ARE NOT REVERSIBLE SETTINGS SWITCHES.
#
# Read `uplers_server/consent_write.py` before touching either. They are NOT
# in AGENT_CONFIG_WRITE_TOOLS and must not be moved there: that group's stated
# property is that everything in it can be put back, and it stops meaning
# anything the moment one of these is filed in it.
#
#   * uplers_revoke_email_scan IS reversible (POST the same URL re-grants) but
#     is a standing PERMISSION rather than a setting, and re-granting starts a
#     fresh scan rather than resuming this one.
#   * uplers_submit_interview_feedback is genuinely ONE-WAY. No edit route, no
#     delete route, complete negative search. Its interview list is currently
#     EMPTY, so it refuses every call today - which is the tool working.
#
# The wrappers stay thin on purpose: the guards that run in production are the
# ones the tests exercise, not a copy of them living here.


@mcp.tool()
async def uplers_revoke_email_scan(confirm: bool = False) -> dict:
    """Stop Uplers scanning your Gmail for job-board alerts. Reversible.

    This is the switch behind `uplers_email_scan()`. It is currently ON and has
    been finding jobs out of your mailbox; this withdraws that permission.

    FOUR THINGS IT DOES AND DOES NOT DO, all measured from Uplers' own product
    rather than assumed, because they are the whole decision:

    IT STOPS FUTURE SCANS ONLY. Uplers' own success message is future tense:
    "Happpy Agent will no longer scan your job board alert emails."

    IT DOES NOT DELETE WHAT THE SCAN ALREADY FOUND, and no route anywhere in
    Uplers does. Complete negative search: the only three DELETE routes in this
    namespace are this consent, the company blocklist, and pending external
    apply jobs. The jobs already pulled out of your mailbox stay where they
    are. If removing them is the point, this is not the tool and there is no
    tool - that is a support request.

    IT DOES NOT DISCONNECT GMAIL. That is a separate grant on a separate route
    (talent/account/gmail/disconnect) which this server does not build. Your
    mailbox stays connected; Uplers stops reading it.

    IT IS REVERSIBLE. A POST to the same URL with an empty body re-grants it.
    That POST is deliberately not built here - re-granting restarts the scan
    from zero rather than resuming, so it is a decision the same size as this
    one and deserves its own preview rather than a flag on this tool.

    With confirm=False it previews and sends nothing. Confirming snapshots the
    current scan record first, sends a DELETE with no body at all, then RE-READS
    the consent - which is more than Uplers' own client does, because its
    revoke never refetches and the reply carries no consent field to check.

    Refuses if the scan is already off: there would be nothing to revoke.

    Args:
        confirm: False previews. True snapshots, then sends, then re-reads.
    """
    async with _talent_client() as client:
        return await consent_write.revoke_email_scan(
            client,
            confirm=confirm,
            send=consent_write.bare_delete_sender_for(
                client, endpoints.EP_CONSENT_EMAIL_JOB_SCAN
            ),
        )


@mcp.tool()
async def uplers_submit_interview_feedback(
    company_id: int, feedback: str, confirm: bool = False
) -> dict:
    """Publish your review of a company you interviewed with. ONE WAY.

    THERE IS NO EDIT ROUTE AND NO DELETE ROUTE FOR SUBMITTED FEEDBACK anywhere
    in Uplers' product - a complete negative search found neither. Once this
    lands you cannot take it back from here, and the snapshot this tool writes
    is local only: it records the interview list as it stood and cannot retract
    what Uplers received. The only thing that can follow it is a second POST
    for the same company, and whether their server overwrites or appends is not
    knowable from their own client. Treat it as final and public.

    MEASURED: YOUR INTERVIEW LIST IS EMPTY. Uplers lists zero companies, so
    there is nothing to give feedback about right now and every call refuses -
    that is this tool working, not failing. The refusal says why the list is
    empty rather than telling you the id was wrong: Uplers builds that list by
    scanning a mailbox, and the consent governing THAT scan reads false. It is
    a different consent from the Gmail job scan, wearing the same field name,
    and there is nothing for you to switch on - its UI ships as styling with
    nothing rendering it.

    The company must be on the live list. A company_id that is not gets refused
    rather than posted, because on a route with no undo a wrong id publishes a
    review against a company you never met.

    With confirm=False it returns the exact two-key body and sends nothing.
    Your text is echoed back in full - this preview is the only chance to read
    it before it is published.

    Args:
        company_id: Uplers' company id, as uplers_my_interviews reports it.
        feedback: your review. Empty text is refused, not sent blank.
        confirm: False previews. True snapshots, then sends, then re-reads.
    """
    async with _talent_client() as client:
        return await consent_write.submit_interview_feedback(
            client,
            company_id,
            feedback,
            confirm=confirm,
            send=outreach_write.json_sender_for(
                client, endpoints.EP_INTERVIEW_FEEDBACK
            ),
        )


def main() -> None:
    # The background sync task is started lazily by the first tool call rather
    # than here: mcp.run() owns the event loop, and a task created before it
    # exists would have nowhere to live. See _ensure_scheduler().
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
