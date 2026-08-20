"""Sitemap discovery and record hydration.

The sitemap is the only public enumeration source, and it is NOT an index -
it is a sampler that returns a different, partial slice on every fetch, and
has been observed to include already-closed requisitions. So the contract
here is: parse it, UNION what it gave us into the durable id store, and never
treat absence as deletion.
"""

from __future__ import annotations

import re

from . import config, ids
from .client import UplersClient
from .models import SyncResult
from .store import Store

_URL_RE = re.compile(
    r"<url>\s*<loc>([^<]+)</loc>\s*(?:<lastmod>([^<]*)</lastmod>)?\s*</url>",
    re.IGNORECASE,
)
_HR_IN_URL_RE = re.compile(r"HR\d+")


def parse_sitemap(xml_text: str) -> tuple[dict[str, str | None], int]:
    """Return ({hr_number: lastmod}, total <url> entries seen).

    Entries whose URL carries no HR id (static pages) are counted but not
    returned. Duplicate ids keep the first lastmod seen.
    """
    discovered: dict[str, str | None] = {}
    entries = 0
    for match in _URL_RE.finditer(xml_text):
        entries += 1
        loc, lastmod = match.group(1), (match.group(2) or "").strip() or None
        found = _HR_IN_URL_RE.search(loc)
        if found:
            discovered.setdefault(found.group(0), lastmod)
    if not entries:
        # Defensive: a sitemap laid out differently still yields ids.
        for hr_number in ids.extract_from_text(xml_text):
            discovered.setdefault(hr_number, None)
        entries = len(discovered)
    return (discovered, entries)


async def sync_index(
    store: Store,
    client: UplersClient,
    *,
    hydrate: bool = True,
    fetch_budget: int = config.DEFAULT_SYNC_FETCH_BUDGET,
    refresh_stale: bool = True,
) -> SyncResult:
    """Pull the sitemap, union ids into the store, then fetch missing records.

    Raises UplersError if the sitemap itself cannot be fetched - a sync that
    discovered nothing because the network failed must never look like a sync
    that discovered nothing because there was nothing new.
    """
    xml_text = await client.get_sitemap()
    discovered, entries = parse_sitemap(xml_text)
    new_count, new_by_kind = store.union_ids(discovered)

    id_counts = store.count_ids()
    result = SyncResult(
        sitemap_entries=entries,
        ids_in_this_fetch=len(discovered),
        new_ids=new_count,
        new_native_ids=new_by_kind.get(ids.KIND_NATIVE, 0),
        new_aggregated_ids=new_by_kind.get(ids.KIND_AGGREGATED, 0),
        total_known_ids=id_counts.get("total", 0),
        total_known_native=id_counts.get(ids.KIND_NATIVE, 0),
        total_known_aggregated=id_counts.get(ids.KIND_AGGREGATED, 0),
        total_known_unknown_kind=id_counts.get(ids.KIND_UNKNOWN, 0),
    )
    result.notes.append(
        "The sitemap is non-deterministic (33,160 / 39,608 / 10,811 entries on three "
        "consecutive fetches). Ids are unioned in and never deleted on absence, so "
        "run this repeatedly; the picture only gets more complete."
    )

    native = store.native_ids(newest_first=True)
    if hydrate:
        wanted = (
            store.stale_or_missing(native, config.RECORD_TTL_SECONDS)
            if refresh_stale
            else [h for h in native if h not in store.cached_ids()]
        )
        result.native_records_missing = len(wanted)
        batch = wanted[: max(0, fetch_budget)]
        if len(wanted) > len(batch):
            result.notes.append(
                "%d native record(s) still need fetching; fetch_budget was %d. "
                "Run uplers_sync_index() again to continue."
                % (len(wanted) - len(batch), fetch_budget)
            )
        if batch:
            report = await client.get_records(batch)
            result.records_fetched = store.put_records(report.records)
            result.failures = report.failures
            result.requests_made = report.requests_made
            result.ratelimit_remaining = report.ratelimit_remaining
            if report.aborted_reason:
                result.notes.append("STOPPED EARLY: " + report.aborted_reason)
            if report.failures:
                result.notes.append(
                    "%d record(s) failed to fetch and are listed in `failures`; they were "
                    "NOT silently skipped." % len(report.failures)
                )
    else:
        result.native_records_missing = len(
            [h for h in native if h not in store.cached_ids()]
        )
        result.notes.append("hydrate=False, so no job records were fetched this run.")

    record_counts = store.count_records()
    result.records_cached_total = record_counts["total"]
    result.newest_native = native[:10]
    store.set_meta("last_sync", ids.utcnow_iso())
    return result
