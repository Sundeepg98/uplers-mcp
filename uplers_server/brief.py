"""The daily brief: everything that changed, in as few tokens as possible.

This is the tool that gets called most, so it is the one where waste compounds
hardest. Three rules shape it:

  * **Counts before rows.** Every section reports a number and then at most a
    handful of rows. "31 new, here are the 5 best" costs a fraction of thirty-
    one rows and answers the question better.
  * **Only what moved.** The window runs from the last brief, so the second
    call of a morning is nearly empty by construction, and an alert reports a
    requisition once in its life.
  * **An empty brief is a real answer.** When nothing has changed it says so
    in one line. It never pads, and it never returns an empty section that
    could be mistaken for a failed lookup - a stale index is called out
    explicitly instead.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from . import alerts as alerts_mod, config, fit, ids
from . import policy as policy_mod
from .models import Opportunity
from .profile import ACTIVE_STATUSES

BRIEF_META_KEY = "last_brief_at"
DEFAULT_LOOKBACK_DAYS = 7


def window_start(store, *, since: str | None = None) -> tuple[str, str]:
    """(iso_start, how_it_was_chosen). Never guesses silently."""
    if since:
        text = since.strip()
        if len(text) == 10:
            text += "T00:00:00"
        return (text, "explicit")
    previous = store.get_meta(BRIEF_META_KEY)
    if previous:
        return (previous, "last_brief")
    fallback = datetime.fromisoformat(ids.utcnow_iso()) - timedelta(days=DEFAULT_LOOKBACK_DAYS)
    return (fallback.isoformat(), "first_brief_%dd" % DEFAULT_LOOKBACK_DAYS)


def index_health(store, bound=None) -> tuple[dict, list[str]]:
    """Freshness of the local index, and any warning it deserves.

    The staleness threshold is ``servers.uplers.index_stale_hours``; its
    default is ``config.INDEX_STALE_HOURS``, the literal this used to read
    directly.
    """
    stale_hours = policy_mod.resolve(bound).setting(
        "index_stale_hours", default=config.INDEX_STALE_HOURS)
    counts = store.count_records()
    id_counts = store.count_ids()
    last_sync = store.last_sync
    stale = True
    age_hours = None
    if last_sync:
        try:
            delta = datetime.fromisoformat(ids.utcnow_iso()) - datetime.fromisoformat(last_sync)
            age_hours = round(delta.total_seconds() / 3600.0, 1)
            stale = age_hours > stale_hours
        except ValueError:  # pragma: no cover - we wrote the timestamp
            pass
    unhydrated = store.unhydrated_native_count()
    health = {
        "native_records": counts["native"],
        "last_sync": last_sync,
        "age_hours": age_hours,
    }
    if unhydrated:
        health["unfetched_native_ids"] = unhydrated
    notes: list[str] = []
    if stale:
        notes.append(
            "The local index was last synced %s and is older than %dh. Run "
            "uplers_sync_index() - everything below is computed from cached records."
            % (last_sync or "never", stale_hours)
        )
    return (health, notes)


def _days_since(timestamp: str | None) -> int | None:
    if not timestamp:
        return None
    try:
        delta = datetime.fromisoformat(ids.utcnow_iso()) - datetime.fromisoformat(timestamp)
    except ValueError:
        return None
    return max(0, delta.days)


def new_since(opportunities: list[Opportunity], start: str) -> list[Opportunity]:
    """Native requisitions created on or after `start`, newest first.

    Uses the creation time decoded from the HR number, so this needs no
    network and no `created_at` field the API might stop sending.
    """
    fresh = [opp for opp in opportunities if (opp.posted_at or "") >= start]
    fresh.sort(key=lambda opp: opp.posted_at or "", reverse=True)
    return fresh


def follow_up_due(store, *, stale_days: int | None = None, bound=None) -> list[dict]:
    """Tracked applications sitting in an active status for too long.

    ``stale_days=None`` takes ``servers.uplers.follow_up_stale_days``, whose
    default is ``config.FOLLOW_UP_STALE_DAYS``.
    """
    if stale_days is None:
        stale_days = policy_mod.resolve(bound).setting(
            "follow_up_stale_days", default=config.FOLLOW_UP_STALE_DAYS)
    due = []
    for row in store.list_tracked():
        if row["status"] not in ACTIVE_STATUSES:
            continue
        days = _days_since(row["updated_at"])
        if days is not None and days >= stale_days:
            entry = dict(row)
            entry["days"] = days
            due.append(entry)
    due.sort(key=lambda item: -item["days"])
    return due


def build(
    store,
    profile,
    opportunities: list[Opportunity],
    *,
    limit: int = 5,
    since: str | None = None,
    peek: bool = False,
    alert_rows: int = 3,
    bound=None,
    explain: bool = False,
) -> dict:
    """Assemble the brief. Returns a plain dict the tool wraps in a model.

    ``explain`` reaches both scored sections - the new-requisition ranking and
    the alert hits. The follow-up rows are read straight off tracked local
    state and are never scored, so nothing is added to them.
    """
    bound = policy_mod.resolve(bound)
    start, how = window_start(store, since=since)
    health, notes = index_health(store, bound)
    notes.extend(bound.notes())
    saved_ids = store.saved_ids()
    tracked = store.tracked_ids()
    actions: list[str] = []

    # -- what is new -------------------------------------------------------
    fresh = new_since(opportunities, start)
    ranked, blocked, unscorable = fit.rank(
        fresh, profile,
        exclude_blocked=bound.setting("exclude_blocked", "brief", default=True),
        bound=bound,
        explain=explain,
    )
    new_rows = [
        fit.to_row(
            opp,
            assessment,
            saved=opp.hr_number in saved_ids,
            status=tracked.get(opp.hr_number),
        )
        for opp, assessment in ranked[:limit]
    ]
    new_section = {
        "count": len(fresh),
        "rows": new_rows,
        "note": (
            "%d of %d new requisition(s) have a hard blocker and are not shown; "
            "uplers_rank_opportunities(exclude_blocked=False) shows them."
            % (blocked, len(fresh))
            if blocked
            else None
        ),
    }
    if ranked:
        actions.append(
            "review %d new match(es); best is %s at %s (%d)"
            % (
                len(ranked),
                ranked[0][0].title or ranked[0][0].hr_number,
                ranked[0][0].company or "unnamed client",
                ranked[0][1]["overall_score"],
            )
        )
    if unscorable:
        notes.append(
            "%d new requisition(s) carried neither skills nor an experience band "
            "and are NOT in the counts above: %s. They were left unscored rather "
            "than given jobcore's neutral 50."
            % (len(unscorable), ", ".join(unscorable[:5]))
        )

    # -- alerts ------------------------------------------------------------
    alert_reports = []
    for alert in store.list_alerts():
        try:
            matches = alerts_mod.evaluate(
                opportunities, alert["criteria"], profile, bound=bound,
                explain=explain)
        except Exception as exc:  # noqa: BLE001 - one bad alert must not kill the brief
            notes.append("alert %r could not be evaluated: %s" % (alert["name"], exc))
            continue
        by_id = {opp.hr_number: (opp, assessment) for opp, assessment in matches}
        # Peeking must not consume the news. record_alert_hits WRITES the
        # seen-list, so peek reads it instead and leaves the alert able to
        # report the same matches on the next real brief.
        new_hits = (
            store.unseen_alert_hits(alert["id"], list(by_id))
            if peek
            else store.record_alert_hits(alert["id"], list(by_id))
        )
        if not new_hits:
            continue
        rows = []
        for hr_number in new_hits[:alert_rows]:
            opp, assessment = by_id[hr_number]
            rows.append(
                fit.to_row(
                    opp,
                    assessment,
                    saved=hr_number in saved_ids,
                    status=tracked.get(hr_number),
                    with_flags=False,
                )
            )
        alert_reports.append(
            {
                "id": alert["id"],
                "name": alert["name"],
                "matches": len(by_id),
                "new_matches": len(new_hits),
                "rows": rows,
            }
        )
        if not peek:
            store.mark_hits_notified(alert["id"], new_hits)
    if alert_reports:
        actions.append(
            "%d alert(s) fired: %s"
            % (
                len(alert_reports),
                ", ".join("%s (%d new)" % (a["name"], a["new_matches"]) for a in alert_reports),
            )
        )

    # -- shortlist and pipeline -------------------------------------------
    saved_rows = store.list_saved()
    untracked = [row for row in saved_rows if row["hr_number"] not in tracked]
    shortlist = {"saved": len(saved_rows)}
    if untracked:
        shortlist["not_yet_actioned"] = len(untracked)
        shortlist["oldest"] = [row["hr_number"] for row in untracked[-3:]]
        actions.append(
            "%d shortlisted role(s) have no tracked status yet" % len(untracked)
        )

    pipeline = store.count_tracked_by_status()

    due = follow_up_due(store, bound=bound)
    follow_rows = []
    for row in due[:limit]:
        follow_rows.append(
            {
                "hr_number": row["hr_number"],
                "title": row["title"],
                "company": row["company"],
                "status": row["status"],
                "flags": ["no movement in %d days" % row["days"]],
            }
        )
    if due:
        actions.append("%d application(s) need a follow-up" % len(due))

    if not actions:
        notes.append(
            "Nothing has changed since %s. This is a real 'no news' - the index "
            "holds %d native requisition(s) and every one of them was already "
            "reported." % (start, health["native_records"])
        )

    if not peek:
        store.set_meta(BRIEF_META_KEY, ids.utcnow_iso())

    return {
        "generated_at": ids.utcnow_iso(),
        "since": start,
        "index": health,
        "new_opportunities": new_section,
        "alert_hits": alert_reports,
        "shortlist": shortlist,
        "pipeline": pipeline,
        "follow_up": follow_rows,
        "actions": actions,
        "notes": notes,
        "_window_source": how,
    }
