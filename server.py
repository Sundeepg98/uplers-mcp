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

from uplers_server import __version__, config, ids, search as search_mod, sync as sync_mod
from uplers_server.client import UplersClient, UplersError
from uplers_server.models import (
    MarketStats,
    NewSinceResult,
    OpportunityDetail,
    SearchResult,
    SyncResult,
)
from uplers_server.shaping import to_detail
from uplers_server.store import Store

INSTRUCTIONS = (
    "Read-only reader for the Uplers talent board. Its unique value is the END "
    "CLIENT COMPANY NAME on Uplers-native requisitions, which job boards hide. "
    "Call uplers_sync_index() first (it builds the local index); after that "
    "search, detail lookups and stats are served from the local cache."
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


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
