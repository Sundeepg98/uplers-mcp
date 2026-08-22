"""Project a raw 112-field API record onto the typed models.

Every quirk handled here was observed in real responses, not guessed:
  * YearOfExp / max_yoe / hr_yoe / cost arrive as decimal STRINGS ("5.00").
  * max_yoe == "0.00" means "no upper bound", not "zero years".
  * cost is Indian-grouped ("9,00,000-15,00,000") or the word "Confidential".
  * cost_start_in_dollar is MONTHLY; cost_start_in_dollar_yearly is YEARLY.
  * CompanyName (top level) is the end client; company.company_name is usually null.
  * is_partner_company is a date string ("Jun 2026") or the bool False.
  * JobDescription and company.about are HTML.

FOUR SURFACES, ONE REQUISITION. Uplers serves the same job through four routes
and spells its two most important fields differently on each. That map lives in
:func:`job_view` and :func:`company_name` and NOWHERE ELSE - three copies of a
key map is how this bug recurs, and it already recurred once across three tools.
"""

from __future__ import annotations

import html
import re

from . import config, ids
from .models import (
    Assessment,
    CompanyInfo,
    Opportunity,
    OpportunityDetail,
    PayBand,
    ShiftWindow,
    SkillSet,
)

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"[ \t\r\f\v]+")
_BLANKLINES_RE = re.compile(r"\n{3,}")
_BLOCK_END_RE = re.compile(r"</(p|div|li|h[1-6]|tr|blockquote)\s*>", re.IGNORECASE)
_BREAK_RE = re.compile(r"<br\s*/?>", re.IGNORECASE)
_MONEY_RE = re.compile(r"\d[\d,]*")


def _first(raw: dict, *names: str):
    """First present, non-empty value among several candidate spellings."""
    for name in names:
        value = raw.get(name)
        if value not in (None, "", [], {}):
            return value
    return None


def html_to_text(raw: str | None) -> str | None:
    """Flatten HTML to readable plain text, preserving paragraph breaks."""
    if not raw:
        return None
    text = _BREAK_RE.sub("\n", raw)
    text = _BLOCK_END_RE.sub("\n\n", text)
    text = _TAG_RE.sub("", text)
    text = html.unescape(text)
    text = _WS_RE.sub(" ", text)
    text = "\n".join(line.strip() for line in text.split("\n"))
    text = _BLANKLINES_RE.sub("\n\n", text).strip()
    return text or None


def to_float(value) -> float | None:
    """Decimal-string / number to float. Empty, None and junk become None."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def to_int(value) -> int | None:
    number = to_float(value)
    return int(number) if number is not None else None


def parse_local_band(cost) -> tuple[int | None, int | None]:
    """Parse the local-currency band out of the `cost` string.

    "9,00,000-15,00,000" gives (900000, 1500000); "Confidential" gives
    (None, None); a single number gives that number twice.
    """
    if not isinstance(cost, str):
        return (None, None)
    numbers = [int(m.group(0).replace(",", "")) for m in _MONEY_RE.finditer(cost)]
    if not numbers:
        return (None, None)
    if len(numbers) == 1:
        return (numbers[0], numbers[0])
    return (min(numbers), max(numbers))


def _truthy_confidential(raw: dict) -> bool:
    if to_int(raw.get("IsConfidentialBudget")):
        return True
    return str(raw.get("cost_string") or "").strip().lower() == "confidential"


def pay_period(cost_string) -> str | None:
    """Uplers quotes contract roles monthly and permanent roles yearly."""
    text = str(cost_string or "").lower()
    if "/ month" in text or "/month" in text:
        return "month"
    if "/ year" in text or "/year" in text:
        return "year"
    return None


def _is_ceiling(cost_string) -> bool:
    """'Upto INR 30,00,000 / year' states a maximum, not a point value."""
    text = str(cost_string or "").strip().lower()
    return text.startswith("upto") or text.startswith("up to")


def build_pay(raw: dict) -> PayBand:
    cost_string = raw.get("cost_string")
    local_min, local_max = parse_local_band(raw.get("cost"))
    if _is_ceiling(cost_string) and local_min == local_max:
        local_min = None  # a stated ceiling has no floor
    return PayBand(
        currency=raw.get("Currency") or None,
        text=(cost_string or "").strip() or None,
        local_min=local_min,
        local_max=local_max,
        local_period=pay_period(cost_string),
        usd_year_min=to_int(raw.get("cost_start_in_dollar_yearly")) or None,
        usd_year_max=to_int(raw.get("cost_end_in_dollar_yearly")) or None,
        confidential=_truthy_confidential(raw),
    )


def build_skills(raw: dict) -> SkillSet:
    must, good = [], []
    for entry in raw.get("skills") or []:
        skill = (entry or {}).get("skill") or {}
        name = (skill.get("name") or "").strip()
        if not name:
            continue
        if skill.get("type") == "must_have":
            must.append(name)
        else:
            good.append(name)
    return SkillSet(must_have=must, good_to_have=good)


def build_shift(raw: dict) -> ShiftWindow:
    shifts = raw.get("shifts") or []
    first = shifts[0] if shifts and isinstance(shifts[0], dict) else {}
    return ShiftWindow(
        timezone=first.get("shift") or raw.get("HR_ShiftTime") or None,
        start_time=first.get("start_time") or None,
        end_time=first.get("end_time") or None,
        ist_window=first.get("ist_shift_time") or None,
    )


def build_company(raw: dict) -> CompanyInfo:
    company = raw.get("company") or {}
    about = html_to_text(company.get("about"))
    if about and len(about) > config.COMPANY_ABOUT_PREVIEW_CHARS:
        about = about[: config.COMPANY_ABOUT_PREVIEW_CHARS].rstrip() + " ..."
    return CompanyInfo(
        # One map, shared with `to_opportunity`. On the public catalogue this is
        # top-level `CompanyName`; on the authenticated tiers it is nested.
        name=company_name(raw),
        industry=company.get("industry") or None,
        team_size=str(company["team_size"]) if company.get("team_size") else None,
        website=company.get("website_url") or None,
        linkedin=company.get("linkedin_url") or None,
        about=about,
    )


def build_assessments(raw: dict) -> list[Assessment]:
    out = []
    for entry in raw.get("assessments") or []:
        if not isinstance(entry, dict):
            continue
        nested = entry.get("assessment") or {}
        duration = entry.get("duration_formatted") or entry.get("duration") or ""
        out.append(
            Assessment(
                name=entry.get("name") or nested.get("name") or None,
                tool=entry.get("assessment_tool") or None,
                duration=str(duration).strip() or None,
                difficulty=entry.get("difficulty") or None,
            )
        )
    return out


def _city(raw: dict) -> str | None:
    if raw.get("city"):
        return str(raw["city"])
    city_data = raw.get("city_data")
    if isinstance(city_data, dict):
        for key in ("name", "city_name", "city"):
            if city_data.get(key):
                return str(city_data[key])
    locations = raw.get("job_location") or []
    if locations and isinstance(locations[0], dict):
        for key in ("name", "city", "location"):
            if locations[0].get(key):
                return str(locations[0][key])
    return None


def _max_yoe(raw: dict) -> float | None:
    """max_yoe of 0 means "no upper bound", which is not the same as zero."""
    value = to_float(raw.get("max_yoe"))
    if value is None or value <= 0:
        return None
    return value


def _company_obj(raw: dict) -> dict:
    """The `company` value as a mapping, whatever type the surface sent."""
    value = raw.get("company")
    return value if isinstance(value, dict) else {}


#: The key under which `talent/hr/my-opportunities` nests the requisition. That
#: route returns HIS APPLICATIONS, so its row is the application and the job
#: hangs off it - which is the right shape for what it is, and the reason a
#: reader written for the catalogue found nothing on it.
JOB_NODE_KEY = "hr"

#: Title, in the order the surfaces are preferred. `RequestForTalent` is the
#: catalogue/feed/pipeline spelling; `title` is `tailor-jobs` alone.
TITLE_KEYS = ("RequestForTalent", "title")

_EXPERIENCE_RE = re.compile(r"\d+(?:\.\d+)?")


def job_view(raw: dict) -> dict:
    """The mapping carrying the JOB's fields, for any of the four surfaces.

    Three of the four put them at the top level and this returns *raw*
    unchanged. `my-opportunities` nests them under ``hr``, and for that one this
    returns the nested node OVERLAID ON the wrapper - nested wins, wrapper fills
    the gaps - because the wrapper still carries a few of the job's own fields
    that the nested node omits (``created_at``, ``is_aggregator_job``).

    **The overlay direction is the load-bearing half, and not only for reading.**
    The wrapper's ``enc_id`` is HIS TALENT id: MEASURED identical across all nine
    of his pipeline rows, while ``hr.enc_id`` differs per row and is the
    requisition's. ``enc_id`` is what the save/unsave route sends as ``hr_id``,
    so a wrapper-first read does not merely mislabel a row - it aims a write at
    the wrong identifier space. The wrapper carries no ``id`` at all, so the
    numeric id ``uplers_apply`` needs was simply absent.
    """
    nested = raw.get(JOB_NODE_KEY)
    if not isinstance(nested, dict):
        return raw
    return {**raw, **nested}


def company_name(raw: dict) -> str | None:
    """The END CLIENT's name, however this surface spells it.

    Three spellings, all live:

    * ``CompanyName`` at the top level - the public catalogue.
    * ``company.company_name`` - the authenticated feed and pipeline, where
      ``CompanyName`` is ABSENT rather than empty. This is the field the
      server's own instructions call its unique value, and it had never once
      been read on the tier that has it.
    * ``company`` as a bare STRING - `tailor-jobs`, which sends the name
      directly rather than an object.

    The name is frequently a deliberate alias ("A Series B Funded Innovative
    Device Trade-In Company - Netherlands") where ``company.is_confidential``
    is set. That is Uplers' own anonymisation and is passed through as given;
    inventing the real name from the website URL beside it is not this
    function's business.
    """
    direct = raw.get("CompanyName")
    if direct:
        return str(direct)
    value = raw.get("company")
    if isinstance(value, dict):
        return value.get("company_name") or None
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def parse_experience_sentence(text) -> tuple[float | None, float | None]:
    """``"3 - 5 Years of Exp"`` -> (3.0, 5.0). Only `tailor-jobs` sends this.

    Every other surface publishes the pair as ``YearOfExp`` / ``max_yoe``.
    MEASURED against `single-hr` on 2026-08-22, which is why the one-number
    form resolves the way it does rather than the way it reads:

        "3 - 5 Years of Exp"  <->  YearOfExp 3.00, max_yoe 5.00
        "2 - 7 Years of Exp"  <->  YearOfExp 2.00, max_yoe 7.00
        "5 Years of Exp"      <->  YearOfExp 5.00, max_yoe 0.00

    So a lone number is the FLOOR with no ceiling, not an exact requirement -
    ``max_yoe`` of 0 being Uplers' "no upper bound", handled in :func:`_max_yoe`.
    """
    if not isinstance(text, str):
        return (None, None)
    numbers = [float(m.group(0)) for m in _EXPERIENCE_RE.finditer(text)]
    if not numbers:
        return (None, None)
    if len(numbers) == 1:
        return (numbers[0], None)
    return (min(numbers), max(numbers))


def to_opportunity(raw: dict) -> Opportunity:
    raw = job_view(raw)
    hr_number = ids.normalise(str(raw.get("HR_Number") or ""))
    detail = raw.get("detail") or {}
    sentence_min, sentence_max = parse_experience_sentence(raw.get("experience"))
    return Opportunity(
        hr_number=hr_number,
        title=_first(raw, *TITLE_KEYS),
        role=raw.get("HR_Role") or detail.get("standardized_title") or None,
        company=company_name(raw),
        # `company` is an object on every surface except `talent/hr/tailor-jobs`,
        # which sends the pitch as a bare string. `or {}` guards a falsy value,
        # not a wrong type, so the isinstance check is the load-bearing half.
        industry=(_company_obj(raw).get("industry") or None),
        mode_of_work=raw.get("ModeOfWork") or None,
        city=_city(raw),
        min_years_experience=to_float(raw.get("YearOfExp")) or sentence_min,
        max_years_experience=_max_yoe(raw) or sentence_max,
        pay=build_pay(raw),
        joining_period=raw.get("joining_period") or raw.get("HowSoon") or None,
        availability=raw.get("Availability") or None,
        duration_type=raw.get("DurationType") or None,
        skills=build_skills(raw),
        assessments_required=len(raw.get("assessments") or []),
        posted_at=ids.created_at_iso(hr_number),
        created_at=raw.get("created_at") or None,
        is_native=not bool(raw.get("is_aggregator_job")),
        job_nature=raw.get("job_nature") or None,
        talents_count=to_int(raw.get("talents_count")),
        url=config.OPPORTUNITY_URL.format(hr_number=hr_number) if hr_number else None,
    )


def to_detail(raw: dict, *, full_description: bool = False) -> OpportunityDetail:
    # Same view as `to_opportunity`, resolved once here so every read below -
    # description, company block, shift, assessments - sees the job node rather
    # than whatever wraps it.
    raw = job_view(raw)
    base = to_opportunity(raw).model_dump()
    description = html_to_text(raw.get("JobDescription"))
    truncated = False
    if description and not full_description and len(description) > config.DESCRIPTION_PREVIEW_CHARS:
        description = description[: config.DESCRIPTION_PREVIEW_CHARS].rstrip() + " ..."
        truncated = True
    detail = raw.get("detail") or {}
    return OpportunityDetail(
        **base,
        description=description,
        description_truncated=truncated,
        company_info=build_company(raw),
        shift=build_shift(raw),
        assessments=build_assessments(raw),
        office_visit_frequency=(
            raw.get("frequency_office_visit") or detail.get("frequency_office_visit") or None
        ),
        hiring_model=raw.get("PricingName") or raw.get("pricingModel") or None,
        payroll=raw.get("PayrollType") or None,
        positions_open=to_int(raw.get("Quantity")),
        status_note=raw.get("HR_Status") or None,
        experience_flexible=bool(to_int(raw.get("is_experience_flexible"))),
    )
