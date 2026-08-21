"""Two questions the listing tools cannot answer.

**Skill gap.** Not "what skills are popular" - that is what
uplers_get_market_stats already reports. The useful question is narrower and
personal: *which single skill, if you had it, would move the most
requisitions from ineligible to eligible?* That is `sole_blocker` - the count
of roles where a skill is the ONLY must-have you are missing. A skill named by
forty roles you would fail anyway is worth less than one named by six you
would otherwise pass, and only the second number tells you where an evening of
study pays.

**Company intel.** The end client name is the reason this server exists, so
the natural follow-up is "who are they, and what else do they have open".
Everything comes from records already cached; there is no company endpoint and
no second request.
"""

from __future__ import annotations

from statistics import median

from . import fit, policy as policy_mod
from .models import Opportunity
from .shaping import build_company


def _pay(opp: Opportunity) -> int | None:
    """One comparable figure per requisition: the top of the USD/year band."""
    return opp.pay.usd_year_max or opp.pay.usd_year_min


def skill_demand(opportunities: list[Opportunity], profile_skills: set, bound=None) -> dict[str, dict]:
    """Per canonical skill: how many roles want it, how many demand it, what it pays.

    `sole_blocker` counts roles whose unmet must-have set is exactly this one
    skill - the roles that learning it alone would unlock.
    """
    demand: dict[str, dict] = {}

    def bucket(name: str) -> dict:
        return demand.setdefault(
            name,
            {"roles": 0, "as_must_have": 0, "sole_blocker": 0, "pays": [], "companies": []},
        )

    for opp in opportunities:
        must = fit.parse_skills(opp.skills.must_have, bound)
        good = fit.parse_skills(opp.skills.good_to_have, bound)
        pay = _pay(opp)
        for name in must | good:
            entry = bucket(name)
            entry["roles"] += 1
            if name in must:
                entry["as_must_have"] += 1
            if pay:
                entry["pays"].append(pay)
            if opp.company and opp.company not in entry["companies"]:
                entry["companies"].append(opp.company)
        unmet = must - profile_skills
        if len(unmet) == 1:
            bucket(next(iter(unmet)))["sole_blocker"] += 1

    return demand


def skill_gap(
    opportunities: list[Opportunity],
    profile,
    *,
    top: int = 12,
    min_roles: int = 2,
    bound=None,
) -> dict:
    """Your skills against the board's demand, and what is worth learning."""
    bound = policy_mod.resolve(bound)
    mine = fit.parse_skills(profile.skills, bound)
    demand = skill_demand(opportunities, mine, bound)
    all_pays = [pay for pay in (_pay(opp) for opp in opportunities) if pay]
    cohort_median = int(median(all_pays)) if all_pays else None

    def row(name: str, entry: dict) -> dict:
        pays = entry["pays"]
        skill_median = int(median(pays)) if pays else None
        return {
            "skill": name,
            "roles": entry["roles"],
            "as_must_have": entry["as_must_have"] or None,
            "sole_blocker": entry["sole_blocker"] or None,
            "median_pay_usd": skill_median,
            "pay_delta_usd": (
                skill_median - cohort_median
                if skill_median is not None and cohort_median is not None
                else None
            ),
            "example_companies": entry["companies"][:3],
        }

    have = [
        row(name, entry)
        for name, entry in demand.items()
        if name in mine and entry["roles"] >= min_roles
    ]
    have.sort(key=lambda item: (-item["roles"], item["skill"]))

    missing = [
        row(name, entry)
        for name, entry in demand.items()
        if name not in mine and entry["roles"] >= min_roles
    ]
    # The unlock question first, then raw demand. A skill that gates six roles
    # you would otherwise pass beats one mentioned by forty you would fail.
    missing.sort(
        key=lambda item: (
            -(item["sole_blocker"] or 0),
            -(item["as_must_have"] or 0),
            -item["roles"],
            item["skill"],
        )
    )

    unused = sorted(name for name in mine if name not in demand)
    demanded = set(demand)
    return {
        "population": len(opportunities),
        "cohort_median_pay_usd": cohort_median,
        "your_skills_in_demand": have[:top],
        "missing_skills": missing[:top],
        "unused_skills": unused[:20],
        "coverage": "%d of %d skills the board asks for"
        % (len(mine & demanded), len(demanded)),
    }


# --- company intel --------------------------------------------------------


def _tally(values) -> dict[str, int]:
    out: dict[str, int] = {}
    for value in values:
        if value:
            out[value] = out.get(value, 0) + 1
    return dict(sorted(out.items(), key=lambda kv: (-kv[1], kv[0])))


def find_company(pairs: list[tuple[dict, Opportunity]], name: str):
    """Resolve a company query to one end client.

    Returns (matched_pairs, candidate_names). An exact (case-insensitive) name
    wins outright; otherwise a substring that hits several distinct clients
    returns no matches and the candidate list, because silently picking the
    biggest one would answer a question nobody asked.
    """
    needle = (name or "").strip().lower()
    if not needle:
        return ([], [])
    hits = [(raw, opp) for raw, opp in pairs if needle in (opp.company or "").lower()]
    if not hits:
        return ([], [])
    distinct = sorted({opp.company for _, opp in hits if opp.company})
    exact = [company for company in distinct if company.lower() == needle]
    chosen = exact[0] if exact else (distinct[0] if len(distinct) == 1 else None)
    if chosen is None:
        return ([], distinct)
    return ([(raw, opp) for raw, opp in hits if opp.company == chosen], distinct)


def company_intel(pairs: list[tuple[dict, Opportunity]], name: str, profile=None,
                  *, bound=None) -> dict:
    """Everything cached about one end client, plus its aggregate posture."""
    hits, candidates = find_company(pairs, name)
    if not hits:
        return {"company": name, "open_requisitions": 0, "candidates": candidates[:15]}

    raws = [raw for raw, _ in hits]
    opps = [opp for _, opp in hits]
    company = build_company(raws[0])
    pays = [pay for pay in (_pay(opp) for opp in opps) if pay]
    yoes = [opp.min_years_experience for opp in opps if opp.min_years_experience is not None]
    posted = sorted(opp.posted_at for opp in opps if opp.posted_at)
    skills = _tally(
        skill
        for opp in opps
        for skill in (opp.skills.must_have + opp.skills.good_to_have)
    )

    intel = {
        "company": opps[0].company,
        "industry": company.industry,
        "team_size": company.team_size,
        "website": company.website,
        "linkedin": company.linkedin,
        "about": company.about,
        "open_requisitions": len(opps),
        "roles": sorted({opp.role or opp.title for opp in opps if (opp.role or opp.title)})[:10],
        "pay_usd_year": (
            "$%d-%d" % (min(pays), max(pays)) if len(pays) > 1 and min(pays) != max(pays)
            else ("$%d" % pays[0] if pays else None)
        ),
        "modes": _tally(opp.mode_of_work for opp in opps),
        "joining_periods": _tally(opp.joining_period for opp in opps),
        "top_skills": list(skills)[:10],
        "assessments_required": sum(opp.assessments_required for opp in opps) or None,
        "first_posted": posted[0] if posted else None,
        "latest_posted": posted[-1] if posted else None,
        "median_min_yoe": round(median(yoes), 1) if yoes else None,
        "candidates": [c for c in candidates if c != opps[0].company][:10],
    }
    if profile is not None:
        # Deliberately NOT servers.uplers.exclude_blocked.*: this is an
        # aggregate posture over everything the client has open, not a
        # shortlist he is meant to act on.
        ranked, _ = fit.rank(opps, profile, exclude_blocked=False, bound=bound)
        intel["_ranked"] = ranked
    return intel
