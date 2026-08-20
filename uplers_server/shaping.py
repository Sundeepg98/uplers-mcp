"""Project a raw 112-field API record onto the typed models.

Every quirk handled here was observed in real responses, not guessed:
  * YearOfExp / max_yoe / hr_yoe / cost arrive as decimal STRINGS ("5.00").
  * max_yoe == "0.00" means "no upper bound", not "zero years".
  * cost is Indian-grouped ("9,00,000-15,00,000") or the word "Confidential".
  * cost_start_in_dollar is MONTHLY; cost_start_in_dollar_yearly is YEARLY.
  * CompanyName (top level) is the end client; company.company_name is usually null.
  * is_partner_company is a date string ("Jun 2026") or the bool False.
  * JobDescription and company.about are HTML.
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
        # Top-level CompanyName is the end client; company.company_name is
        # almost always null. Prefer whichever is actually populated.
        name=raw.get("CompanyName") or company.get("company_name") or None,
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


def to_opportunity(raw: dict) -> Opportunity:
    hr_number = ids.normalise(str(raw.get("HR_Number") or ""))
    detail = raw.get("detail") or {}
    return Opportunity(
        hr_number=hr_number,
        title=raw.get("RequestForTalent") or None,
        role=raw.get("HR_Role") or detail.get("standardized_title") or None,
        company=raw.get("CompanyName") or None,
        industry=(raw.get("company") or {}).get("industry") or None,
        mode_of_work=raw.get("ModeOfWork") or None,
        city=_city(raw),
        min_years_experience=to_float(raw.get("YearOfExp")),
        max_years_experience=_max_yoe(raw),
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
