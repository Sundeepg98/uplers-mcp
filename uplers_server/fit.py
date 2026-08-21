"""Fit scoring: the adapter between an Uplers requisition and jobcore.

**No scoring maths lives here, and no configuration is read here.** The
88-skill taxonomy, the skill/experience split, the over-qualification curve
and the bonus table are all `jobcore`'s, shared with the Naukri server so a
fit score means the same thing on both boards. The numbers that drive them
come from the shared `jobhunt.json` via :mod:`uplers_server.policy`, which is
bound ONCE at tool entry and handed down as a `bound` argument. This module
does no I/O at all: the same requisition must score the same on two machines,
or a score stops meaning anything.

`bound=None` means "the shipped defaults", which are exactly the literals
this module used to carry. A clone with no config file anywhere scores
byte-for-byte as it did before any of this existed.

This module's whole job is translation, and it is honest about the three
places where Uplers' data does not map cleanly:

1. **Units.** jobcore's Salary is denominated in "lakhs" only because that is
   what its first consumer used; the unit is injected. Uplers publishes a
   USD/year normalisation, so a Salary type is bound with
   ``lakhs_multiplier=1.0`` and the numbers ARE dollars per year. The local
   currency string is deliberately NOT passed - handing
   "INR 9,00,000-15,00,000 / year" to a dollar-denominated parser would read
   900,000 as a US salary and score every Indian role as a windfall. For the
   same reason his pay expectations are read from
   ``candidate.pay.usd_per_year`` and never from the lakhs band beside it.

2. **Unbounded experience.** Uplers writes ``max_yoe = 0`` to mean "no upper
   bound". Passing 0 would score every experienced candidate as wildly
   over-qualified, so an unbounded ceiling is raised to the candidate's own
   years - which is precisely what "no upper bound" means for them.

3. **Must-have vs good-to-have.** jobcore scores one flat skill set. Uplers
   types its skills, and that split is real information, so it is reported
   ALONGSIDE the score as `must_have` coverage rather than folded into it.
   Two servers whose scores are computed differently could not be compared,
   and comparability is the reason jobcore exists.

Hard incompatibilities - a notice period the client will not accept, a company
you have excluded - are `blockers`, not score deductions. A 92 that you cannot
take is more useful labelled than quietly turned into a 71.
"""

from __future__ import annotations

from . import policy as policy_mod
from .models import Opportunity
from .policy import USD_YEAR_CONFIG, UsdYearSalary  # re-exported: the units trap
from .search import notice_days

__all__ = [
    "USD_YEAR_CONFIG",
    "UsdYearSalary",
    "assess",
    "blockers_and_flags",
    "compact_verdict",
    "experience_bounds",
    "experience_text",
    "must_have_ratio",
    "parse_skills",
    "preference_tilt",
    "rank",
    "render_pay",
    "to_row",
    "usd_salary_string",
]


def parse_skills(raw, bound=None) -> set:
    """Canonicalise skills through jobcore's shared taxonomy.

    Uses the bound engine's taxonomy, so vocabulary he added under
    ``scoring.skills.extra_skills`` resolves here too rather than only inside
    jobcore.
    """
    return policy_mod.resolve(bound).engine.parse_skills(raw)


# ── Stack preference ─────────────────────────────────────────────────────────
# The operator would still take a Python backend role - he has five years of it
# and it stays on his profile - but Node/TypeScript is the direction he is
# moving in. So a Python-leaning role ranks BELOW an otherwise-comparable Node
# one.
#
# This used to be `PREFERENCE_TILT = 4` plus two hardcoded frozensets, right
# here - his own stated preference, compiled into a server he does not edit.
# It is now `scoring.rank_adjustments` in the shared document, and the shipped
# default is exactly what the constant did, so nothing moved when it was
# deleted. What it is NOT, still:
#
# * not a filter. Python roles are ranked lower, never hidden. `ranked` and
#   `scanned` are unchanged, and the role still appears with its real score.
# * not a score change. `overall_score` stays exactly jobcore's, so a 78 here
#   still means what a 78 means on the Naukri server. Comparability across
#   boards is the reason jobcore exists and a personal stack preference is not
#   allowed to spend it. The adjustment moves the ORDER and is reported
#   separately as `rank_adjustment`.
# * not `scoring.skills.weights`. Weighted coverage is
#   sum(w[matched]) / sum(w[job]), which cancels whenever the matched set
#   equals the job set - the pure-Python role this exists to demote is exactly
#   that case - and RAISES the score of a job asking for a down-weighted skill
#   he lacks. Measured: {node.js, django} scores 50 flat and 58.8 with django
#   at 0.7. A demotion expressed that way runs backwards on the modal case.
#
# Size: still 4 by default, and CLAMPED to 4 in jobcore's Python, deliberately
# just under jobcore's smallest structural bonus (+5 each for location,
# remote, salary fit, agent eligibility). A stack preference should be able to
# decide a near-tie; it should NOT be able to outweigh "this role is actually
# remote". The clamp is applied to the sum, so extra rules cannot stack past
# it either.


def preference_tilt(skills, bound=None) -> tuple:
    """``(delta, labels)`` — the ranking adjustment for a role's stack.

    Never a score change. Returns ``(0, ())`` for a role no rule matches,
    which with the shipped rule is every role that does not lean Python.
    """
    return policy_mod.resolve(bound).scoring.rank_adjustment(skills)


def experience_bounds(
    opp: Opportunity, profile_years: float | None
) -> tuple[float | None, float | None]:
    """(min, max) years for scoring, resolving Uplers' unbounded ceiling."""
    low = opp.min_years_experience
    high = opp.max_years_experience
    if low is None and high is None:
        return (None, None)
    if low is None:
        low = 0.0
    if high is None:
        # "No stated upper bound" - so the candidate cannot be over the top of
        # a band that has no top.
        high = max(low, profile_years if profile_years is not None else low)
    return (float(low), float(high))


def experience_text(low: float | None, high: float | None) -> str | None:
    if low is None:
        return None
    if high is None or high == low:
        return "%g+ years" % low
    return "%g-%g years" % (low, high)


def usd_salary_string(opp: Opportunity) -> str | None:
    """The pay band as a dollar figure jobcore can parse, or None.

    None whenever Uplers gave no USD normalisation - a confidential band or a
    record they never normalised. Returning None costs the +5 salary bonus,
    which is correct: there is no evidence either way.
    """
    low, high = opp.pay.usd_year_min, opp.pay.usd_year_max
    if not low and not high:
        return None
    if low and high:
        return "%d-%d" % (low, high)
    return "%d" % (low or high)


def render_pay(opp: Opportunity) -> str | None:
    """One short human string for a pay band. Token economy over completeness.

    A confidential budget that nonetheless carries a USD normalisation is
    rendered as "confidential (est. ...)" rather than as either half alone.
    Both halves are true and the pairing matters: the client did not publish a
    band, but Uplers' own estimate is what the salary bonus is scored on, and a
    figure that drives a score must be visible next to it.
    """
    pay = opp.pay
    low, high = pay.usd_year_min, pay.usd_year_max

    def k(value: int) -> str:
        return "%.0fk" % (value / 1000.0) if value >= 1000 else str(value)

    if low and high and low != high:
        band = "$%s-%s/yr" % (k(low), k(high))
    elif low or high:
        band = "$%s/yr" % k(low or high)
    else:
        band = None

    if pay.confidential:
        return "confidential (est. %s)" % band if band else "confidential"
    return band or pay.text


def blockers_and_flags(opp: Opportunity, profile, bound=None) -> tuple[list[str], list[str]]:
    """Hard incompatibilities and soft caveats, kept out of the score.

    A blocker means "you cannot or will not take this". A flag means "take a
    look before you spend an evening on it". Which of the two a notice
    shortfall is, and how much slack either check allows, are
    ``servers.uplers.*`` settings whose defaults are the literals this
    function used to carry.
    """
    bound = policy_mod.resolve(bound)
    blockers: list[str] = []
    flags: list[str] = []

    accepted = notice_days(opp.joining_period)
    needed = profile.notice_period_days
    tolerance = bound.setting("notice", "tolerance_days", default=0) or 0
    if needed is not None and accepted is not None and accepted < needed - tolerance:
        line = "notice: client accepts %s, you need %d days" % (
            opp.joining_period, needed,
        )
        if tolerance:
            line += " (%g day slack allowed)" % tolerance
        if bound.setting("notice", "shortfall_blocks", default=True):
            blockers.append(line)
        else:
            flags.append(line)
    elif needed is None:
        flags.append("notice unknown: set notice_period_days on your profile")

    for banned in profile.avoid_companies:
        if banned and opp.company and banned.lower() in opp.company.lower():
            blockers.append("company on your avoid list (%s)" % opp.company)
            break

    slack = bound.setting("experience_slack_years", default=1) or 0
    if (
        profile.years_experience is not None
        and opp.min_years_experience is not None
        and profile.years_experience < opp.min_years_experience - slack
    ):
        blockers.append(
            "experience: needs %g+ yrs, you have %g"
            % (opp.min_years_experience, profile.years_experience)
        )

    wanted_modes = profile.normalised_modes()
    if wanted_modes and opp.mode_of_work and opp.mode_of_work not in wanted_modes:
        flags.append("mode %s, you prefer %s" % (opp.mode_of_work, "/".join(wanted_modes)))

    floor = profile.min_pay_usd_year
    if floor is not None:
        top = opp.pay.usd_year_max or opp.pay.usd_year_min
        if top is not None and top < floor:
            flags.append("pay tops out at $%d, below your $%d floor" % (top, floor))
        elif top is None:
            flags.append("no USD band published, pay unverifiable")

    if opp.assessments_required:
        flags.append("%d assessment(s) required" % opp.assessments_required)

    return (blockers, flags)


def assess(opp: Opportunity, profile, bound=None, *, explain: bool = False) -> dict:
    """Score one requisition against the profile.

    Returns the jobcore result dict plus the Uplers-specific fields:
    ``must_have`` coverage, ``blockers`` and ``flags``.

    ``explain=True`` adds jobcore's ``explain`` block -- the weights, the two
    base components and their weighted combination, the bonus table with the
    cap that was or was not applied, the verdict band, and the ``scoring_hash``
    of the arithmetic that produced the number. It is OFF by default because it
    roughly doubles the size of a scored row and this server's governing
    constraint is token cost. The number is identical either way: the block is
    a readout of the working, never an input to it.
    """
    bound = policy_mod.resolve(bound)
    engine = bound.engine

    must = engine.parse_skills(opp.skills.must_have)
    good = engine.parse_skills(opp.skills.good_to_have)
    mine = engine.parse_skills(profile.skills)

    low, high = experience_bounds(opp, profile.years_experience)
    result = engine.compute_fit_score(
        job_skills=must | good,
        profile_skills=mine,
        job_exp_str=experience_text(low, high) or "",
        profile_exp=profile.years_experience,
        job_location=opp.city or ("Remote" if (opp.mode_of_work or "") == "Remote" else None),
        profile_location=profile.location,
        job_work_mode=opp.mode_of_work,
        job_salary=usd_salary_string(opp),
        # USD/year, always. The lakhs band beside it in the shared document is
        # naukri's and is never read here - one shared scalar would score every
        # job on this board +5 and every job on that one 0, and both look
        # exactly like "no salary data".
        profile_expected_ctc=policy_mod.expected_pay(profile),
        experience_min=low,
        experience_max=high,
        explain=explain,
    )

    covered = must & mine
    result["must_have"] = {
        "required": len(must),
        "covered": len(covered),
        "missing": sorted(must - mine),
    }
    blockers, flags = blockers_and_flags(opp, profile, bound)
    warn_ratio = bound.setting("must_have", "warn_ratio", default=0.5)
    if must and not covered:
        # Measured on the live cohort: a role listing three skills of which the
        # single MUST-HAVE was ".NET" scored 90 against a Node profile, purely
        # because the two good-to-haves (AWS, Azure) matched. The client stated
        # a mandatory requirement and it is entirely unmet - that is an
        # eligibility fact of the same kind as an impossible notice period, so
        # it belongs in blockers rather than being smoothed into the score.
        line = "must-have: none of the %d required skill(s) matched (%s)" % (
            len(must), ", ".join(sorted(must)[:3]),
        )
        if bound.setting("must_have", "zero_coverage_blocks", default=True):
            blockers.append(line)
        else:
            flags.append(line)
    elif must and len(covered) / len(must) < warn_ratio:
        flags.append(
            "covers only %d of %d must-have skills" % (len(covered), len(must))
        )
    if low is None:
        flags.append("role states no experience band; experience scored neutral (50)")

    tilt, labels = preference_tilt(must | good, bound)
    if tilt:
        result["rank_adjustment"] = tilt
        for label in labels:
            flags.append("%s: ranked %+d, score unchanged" % (label, tilt))

    result["blockers"] = blockers
    result["flags"] = flags
    return result


def must_have_ratio(assessment: dict) -> float:
    must = assessment.get("must_have") or {}
    required = must.get("required") or 0
    if not required:
        return 1.0
    return (must.get("covered") or 0) / required


def rank(
    opportunities: list[Opportunity],
    profile,
    *,
    exclude_blocked: bool | None = None,
    bound=None,
    explain: bool = False,
) -> tuple[list[tuple[Opportunity, dict]], int]:
    """Score and order a cohort. Returns (ranked pairs, blocked_count).

    Ordering is jobcore's score adjusted by the stack preference, then the raw
    score, then must-have coverage, then the HR number so the order is total
    and stable. None of these change a score - they decide which of two
    comparable scores a human should look at first.

    ``exclude_blocked=None`` takes ``servers.uplers.exclude_blocked.rank``,
    whose default is today's ``True``.

    ``explain`` is handed straight to :func:`assess`, so every pair carries the
    working as well as the number. It changes no score and no ordering.
    """
    bound = policy_mod.resolve(bound)
    if exclude_blocked is None:
        exclude_blocked = bound.setting("exclude_blocked", "rank", default=True)
    scored: list[tuple[Opportunity, dict]] = []
    blocked = 0
    for opp in opportunities:
        assessment = assess(opp, profile, bound, explain=explain)
        if assessment["blockers"]:
            blocked += 1
            if exclude_blocked:
                continue
        scored.append((opp, assessment))
    scored.sort(
        key=lambda pair: (
            -(pair[1]["overall_score"] + pair[1].get("rank_adjustment", 0)),
            -pair[1]["overall_score"],
            -must_have_ratio(pair[1]),
            pair[0].hr_number,
        )
    )
    return (scored, blocked)


def compact_verdict(assessment: dict) -> str | None:
    """"Strong match - apply confidently" -> "strong".

    Derived from jobcore's own recommendation rather than re-deriving it from
    the score, so a threshold change there is followed here instead of
    silently disagreed with. Repeated on every row of every ranking, the long
    form would be one of the largest token costs in the server.
    """
    text = (assessment or {}).get("recommendation") or ""
    return text.split()[0].lower() if text else None


def to_row(
    opp: Opportunity,
    assessment: dict | None = None,
    *,
    saved: bool | None = None,
    status: str | None = None,
    gaps_limit: int = 3,
    with_flags: bool = True,
):
    """Build the compact ranked row. Empty fields are pruned on serialisation.

    `city` is dropped for Remote roles (it names an office nobody attends) and
    `posted_at` is trimmed to a date - the seconds in an HR number are exact
    but nobody needs them, and they cost nine characters on every row.

    This is a PROJECTION and scores nothing, so it takes no `explain` switch:
    the block rides on the assessment it was asked for and is carried through
    to the row. An assessment scored without one leaves the field None, and
    `Compact` then prunes it off the wire entirely.
    """
    from .models import RankedRow

    must = (assessment or {}).get("must_have") or {}
    gaps = (must.get("missing") or (assessment or {}).get("skill_match", {}).get("missing") or [])
    return RankedRow(
        hr_number=opp.hr_number,
        title=opp.title,
        company=opp.company,
        score=(assessment or {}).get("overall_score"),
        verdict=compact_verdict(assessment) if assessment else None,
        mode=opp.mode_of_work,
        city=None if (opp.mode_of_work or "") == "Remote" else opp.city,
        pay=render_pay(opp),
        notice=opp.joining_period,
        must_have=(
            "%d/%d" % (must.get("covered", 0), must["required"]) if must.get("required") else None
        ),
        gaps=list(gaps)[:gaps_limit],
        flags=((assessment or {}).get("flags") or []) if with_flags else [],
        blockers=(assessment or {}).get("blockers") or [],
        posted_at=(opp.posted_at or "")[:10] or None,
        saved=saved or None,
        status=status,
        explain=(assessment or {}).get("explain"),
    )
