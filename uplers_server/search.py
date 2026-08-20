"""Filtering and aggregation over locally cached records.

There is no public search endpoint on Uplers - `talent/hr/opportunities`
requires a logged-in session. Search therefore runs against the local record
cache built by uplers_sync_index(). The native cohort is only a few hundred
records, so a plain in-Python scan is the right amount of machinery.
"""

from __future__ import annotations

import re
from statistics import median

from .models import MarketStats, Opportunity, PayStats, StatsGroup
from .shaping import to_opportunity

SORTS = ("newest", "oldest", "pay_desc", "pay_asc", "least_competition")
GROUP_BYS = ("role", "skill", "mode_of_work", "currency", "company", "joining_period", "industry")

_NOTICE_RE = re.compile(r"(\d+)")


def notice_days(joining_period: str | None) -> int | None:
    """'30 Days' -> 30, 'Immediately' -> 0, None/unparseable -> None."""
    if not joining_period:
        return None
    text = joining_period.strip().lower()
    if text.startswith("immediat"):
        return 0
    match = _NOTICE_RE.search(text)
    if not match:
        return None
    days = int(match.group(1))
    if "month" in text:
        days *= 30
    elif "week" in text:
        days *= 7
    return days


def _contains(haystack: str | None, needle: str) -> bool:
    return bool(haystack) and needle.lower() in haystack.lower()


def _any_contains(values, needle: str) -> bool:
    return any(_contains(v, needle) for v in values)


def matches(
    opp: Opportunity,
    *,
    skill: str | None = None,
    title: str | None = None,
    company: str | None = None,
    min_yoe: float | None = None,
    max_yoe: float | None = None,
    yoe_admits: float | None = None,
    mode_of_work: str | None = None,
    currency: str | None = None,
    min_pay_usd_year: int | None = None,
    joining_period: str | None = None,
    min_notice_days: int | None = None,
    remote_only: bool = False,
) -> bool:
    """Apply every supplied filter. Unsupplied filters are ignored."""
    if skill and not _any_contains(opp.skills.must_have + opp.skills.good_to_have, skill):
        return False
    if title and not (_contains(opp.title, title) or _contains(opp.role, title)):
        return False
    if company and not _contains(opp.company, company):
        return False

    role_min = opp.min_years_experience
    if min_yoe is not None and (role_min is None or role_min < min_yoe):
        return False
    if max_yoe is not None and (role_min is None or role_min > max_yoe):
        return False
    if yoe_admits is not None:
        if role_min is not None and yoe_admits < role_min:
            return False
        if opp.max_years_experience is not None and yoe_admits > opp.max_years_experience:
            return False

    if remote_only and (opp.mode_of_work or "").lower() != "remote":
        return False
    if mode_of_work and (opp.mode_of_work or "").lower() != mode_of_work.lower():
        return False
    if currency and (opp.pay.currency or "").upper() != currency.upper():
        return False
    if min_pay_usd_year is not None:
        # Compared against Uplers' OWN USD/year normalisation, which it
        # publishes for every requisition whatever the local currency - so an
        # INR band and a USD band are already commensurable here and no
        # exchange rate is applied by this server. See README, "The pay floor".
        top = opp.pay.usd_year_max or opp.pay.usd_year_min
        # UNKNOWN PAY IS NOT PAY BELOW THE FLOOR. A requisition with no
        # published figure is admitted and flagged ("no USD band published,
        # pay unverifiable" in blockers_and_flags), never dropped: 47% of this
        # board hides its budget, and a floor that silently deleted them would
        # remove half the index while reporting nothing.
        if top is not None and top < min_pay_usd_year:
            return False
    if joining_period and not _contains(opp.joining_period, joining_period):
        return False
    if min_notice_days is not None:
        days = notice_days(opp.joining_period)
        if days is None or days < min_notice_days:
            return False
    return True


def _sort_spec(sort: str):
    """Return (key_function, reverse) for a supported sort name."""
    if sort == "pay_desc":
        return (lambda o: (o.pay.usd_year_max or o.pay.usd_year_min or 0), True)
    if sort == "pay_asc":
        return (lambda o: (o.pay.usd_year_min or o.pay.usd_year_max or 10**9), False)
    if sort == "least_competition":
        return (lambda o: (o.talents_count if o.talents_count is not None else 10**9), False)
    if sort == "oldest":
        return (lambda o: (o.posted_at or o.created_at or ""), False)
    return (lambda o: (o.posted_at or o.created_at or ""), True)  # newest


def search_records(raw_records, *, sort: str = "newest", limit: int | None = None, **filters):
    """Shape, filter and sort. Returns (results, matched_total, scanned_total)."""
    scanned = 0
    hits: list[Opportunity] = []
    for raw in raw_records:
        scanned += 1
        opp = to_opportunity(raw)
        if matches(opp, **filters):
            hits.append(opp)
    key_fn, reverse = _sort_spec(sort if sort in SORTS else "newest")
    hits.sort(key=key_fn, reverse=reverse)
    matched = len(hits)
    if limit is not None:
        hits = hits[:limit]
    return (hits, matched, scanned)


# --- market statistics ----------------------------------------------------


def _percentile(values: list[int], fraction: float) -> int | None:
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int(round(fraction * (len(ordered) - 1)))))
    return ordered[index]


def _pay_stats(group: list[Opportunity]) -> PayStats:
    lows = [o.pay.usd_year_min for o in group if o.pay.usd_year_min]
    highs = [o.pay.usd_year_max for o in group if o.pay.usd_year_max]
    return PayStats(
        n_with_pay=len([o for o in group if o.pay.usd_year_min or o.pay.usd_year_max]),
        usd_year_min_p25=_percentile(lows, 0.25),
        usd_year_min_median=_percentile(lows, 0.50),
        usd_year_min_p75=_percentile(lows, 0.75),
        usd_year_max_median=_percentile(highs, 0.50),
        usd_year_overall_low=min(lows) if lows else None,
        usd_year_overall_high=max(highs) if highs else None,
    )


def _tally(values) -> dict[str, int]:
    out: dict[str, int] = {}
    for value in values:
        if value:
            out[value] = out.get(value, 0) + 1
    return dict(sorted(out.items(), key=lambda kv: (-kv[1], kv[0])))


def _build_group(key: str, group: list[Opportunity], top_skills: int = 8) -> StatsGroup:
    yoes = [o.min_years_experience for o in group if o.min_years_experience is not None]
    skills = _tally(s for o in group for s in (o.skills.must_have + o.skills.good_to_have))
    remote = [o for o in group if (o.mode_of_work or "").lower() == "remote"]
    companies = [o.company for o in group if o.company]
    return StatsGroup(
        key=key,
        count=len(group),
        pay=_pay_stats(group),
        median_min_yoe=round(median(yoes), 1) if yoes else None,
        remote_share=round(len(remote) / len(group), 2) if group else None,
        top_skills=list(skills)[:top_skills],
        currencies=_tally(o.pay.currency for o in group),
        joining_periods=_tally(o.joining_period for o in group),
        example_companies=sorted(set(companies))[:5],
    )


def _group_keys(opp: Opportunity, group_by: str) -> list[str]:
    if group_by == "role":
        return [opp.role or opp.title or "(untitled)"]
    if group_by == "skill":
        return sorted(set(opp.skills.must_have + opp.skills.good_to_have)) or ["(no skills listed)"]
    if group_by == "mode_of_work":
        return [opp.mode_of_work or "(unspecified)"]
    if group_by == "currency":
        return [opp.pay.currency or "(unspecified)"]
    if group_by == "company":
        return [opp.company or "(unnamed)"]
    if group_by == "joining_period":
        return [opp.joining_period or "(unspecified)"]
    if group_by == "industry":
        return [opp.industry or "(unspecified)"]
    return [opp.role or opp.title or "(untitled)"]


def market_stats(
    raw_records,
    *,
    group_by: str = "role",
    min_group_size: int = 2,
    top_groups: int = 20,
    cohort: str = "native",
    filters_applied: dict | None = None,
    **filters,
) -> MarketStats:
    """Aggregate pay / YoE / skills across the cached cohort."""
    if group_by not in GROUP_BYS:
        group_by = "role"
    population: list[Opportunity] = []
    for raw in raw_records:
        opp = to_opportunity(raw)
        if matches(opp, **filters):
            population.append(opp)

    buckets: dict[str, list[Opportunity]] = {}
    for opp in population:
        for key in _group_keys(opp, group_by):
            buckets.setdefault(key, []).append(opp)

    groups = [
        _build_group(key, members)
        for key, members in buckets.items()
        if len(members) >= min_group_size
    ]
    groups.sort(key=lambda g: (-g.count, g.key))

    notes = []
    dropped = len(buckets) - len(groups)
    if dropped > 0:
        notes.append(
            "%d group(s) below min_group_size=%d were omitted; lower it to see the long tail."
            % (dropped, min_group_size)
        )
    if not population:
        notes.append(
            "No cached record matched these filters, so there is nothing to aggregate. "
            "This is a real zero, not a fetch failure."
        )

    return MarketStats(
        group_by=group_by,
        cohort=cohort,
        population=len(population),
        groups=groups[:top_groups],
        overall=_build_group("ALL", population, top_skills=15) if population else None,
        filters_applied=filters_applied or {},
        notes=notes,
    )
