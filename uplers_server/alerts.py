"""Saved criteria, evaluated locally against the native cohort.

There is no Uplers alert API to call and no email to subscribe to - and that
is the point. An alert here is a stored filter that runs against the index
this server already keeps, so evaluating twenty alerts costs zero network
requests and a few milliseconds. The only cost is the sync that would have
happened anyway.

An alert reports each requisition exactly once. `alert_hits` records what has
already been shown, so the daily brief says "3 new" and means it, instead of
re-reporting the same eleven roles every morning until they are ignored.
Editing an alert's criteria clears that memory, because a widened alert that
stayed silent about the matches it now covers would be a bug.
"""

from __future__ import annotations

from . import fit, policy as policy_mod, search
from .models import Opportunity

# The filter vocabulary an alert may use. Deliberately the same names as
# uplers_search_opportunities, so anything that can be searched can be saved.
FILTER_KEYS = (
    "skill",
    "title",
    "company",
    "min_yoe",
    "max_yoe",
    "yoe_admits",
    "mode_of_work",
    "remote_only",
    "currency",
    "min_pay_usd_year",
    "joining_period",
    "min_notice_days",
)

# Criteria that are not search filters and are applied after scoring.
SCORE_KEYS = ("min_score", "exclude_blocked")

CRITERIA_KEYS = FILTER_KEYS + SCORE_KEYS


class AlertError(ValueError):
    """A criteria dict this server cannot honour. Never silently narrowed."""


def normalise_criteria(raw: dict) -> dict:
    """Drop empties, reject unknown keys loudly.

    An unknown key is an error rather than a shrug: an alert saved with
    `min_salary` when the field is `min_pay_usd_year` would match everything
    forever and look like it was working.
    """
    unknown = sorted(set(raw) - set(CRITERIA_KEYS))
    if unknown:
        raise AlertError(
            "Unknown alert criteria %s. Supported: %s."
            % (", ".join(unknown), ", ".join(CRITERIA_KEYS))
        )
    cleaned = {
        key: value
        for key, value in raw.items()
        if value is not None and value is not False and value != ""
    }
    if not cleaned:
        raise AlertError(
            "An alert with no criteria would match every requisition on the board. "
            "Give it at least one of: %s." % ", ".join(CRITERIA_KEYS)
        )
    return cleaned


def split_criteria(criteria: dict) -> tuple[dict, dict]:
    """(search filters, post-scoring criteria)."""
    filters = {key: value for key, value in criteria.items() if key in FILTER_KEYS}
    scoring = {key: value for key, value in criteria.items() if key in SCORE_KEYS}
    return (filters, scoring)


def evaluate(
    opportunities: list[Opportunity], criteria: dict, profile=None, *, bound=None,
    explain: bool = False,
) -> list[tuple[Opportunity, dict | None]]:
    """Which requisitions match. Returns (opportunity, assessment-or-None) pairs.

    Without a profile there is nothing to score against, so the filters alone
    decide and every assessment is None. That is not a degraded mode: an alert
    for "remote Node roles" is a perfectly good alert, and skipping the scoring
    pass keeps it free.

    With a profile, every hit is scored - the caller wants the numbers for
    display even when the criteria carry no `min_score` gate.

    ``explain`` rides along to :func:`fit.assess`. Without a profile there is
    no assessment to hang it on, so it is silently a no-op there rather than
    an error: the alert still matches exactly what it matched before.
    """
    # Validate at READ time too, not only when the alert was saved. Criteria
    # come out of sqlite, where a row could have been written by an older
    # version or edited by hand; split_criteria silently DROPS keys it does not
    # recognise, so an unvalidated bad key would leave zero filters and quietly
    # match the entire board - the exact failure normalise_criteria exists to
    # prevent.
    criteria = normalise_criteria(criteria)
    filters, scoring = split_criteria(criteria)
    hits = [opp for opp in opportunities if search.matches(opp, **filters)]
    if profile is None:
        if scoring.get("min_score") is not None:
            raise AlertError(
                "This alert has min_score=%s but no profile was supplied, so no score "
                "can be computed. Set a profile with uplers_set_profile()."
                % scoring["min_score"]
            )
        return [(opp, None) for opp in hits]

    bound = policy_mod.resolve(bound)
    min_score = scoring.get("min_score")
    # An alert that does not state a preference takes
    # servers.uplers.exclude_blocked.alerts, whose default is today's False.
    exclude_blocked = scoring.get(
        "exclude_blocked",
        bound.setting("exclude_blocked", "alerts", default=False),
    )
    scored: list[tuple[Opportunity, dict | None]] = []
    for opp in hits:
        try:
            assessment = fit.assess(opp, profile, bound, explain=explain)
        except fit.UnscorableOpportunity:
            # An alert is a filter over scores, so a record that cannot be
            # scored cannot pass one. Dropping it is the only honest answer:
            # admitting it at jobcore's neutral 50 would fire alerts whose
            # min_score is 50 or lower on records nobody has read.
            continue
        if exclude_blocked and assessment["blockers"]:
            continue
        if min_score is not None and assessment["overall_score"] < min_score:
            continue
        scored.append((opp, assessment))
    scored.sort(key=lambda pair: -(pair[1] or {}).get("overall_score", 0))
    return scored


def describe(criteria: dict) -> str:
    """A one-line rendering, for briefs that must not spend tokens on a dict."""
    return ", ".join("%s=%s" % (key, criteria[key]) for key in sorted(criteria))
