"""The candidate profile that every scoring tool keys off.

Stored as `data/profile.json` rather than in sqlite for one reason: a human
should be able to open it, see exactly what the fit scores are being computed
against, and fix a wrong line with a text editor. Nothing else in this server
is meant to be hand-edited; this is.

First use bootstraps it from a résumé markdown file, so the operator does not
start by typing their own CV into a tool call. The parser is deliberately
narrow - it reads the specific structure of the résumé in
`job-hunting/resumes/`, and says so when it cannot find a section, rather than
inventing a plausible profile out of nothing.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

from pydantic import BaseModel, Field

from . import config, ids

# Statuses that a tracked application may hold. Anything else is rejected
# loudly, because a typo'd status silently creates a second bucket that no
# follow-up query will ever look in.
TRACK_STATUSES = (
    "interested",
    "applied_manually",
    "responded",
    "interviewing",
    "rejected",
    "closed",
)

# Statuses that mean the requisition is still live for you.
ACTIVE_STATUSES = ("interested", "applied_manually", "responded", "interviewing")

MODES = ("Remote", "Hybrid", "Office")


class ProfileError(RuntimeError):
    """The profile is missing or unusable. Never silently substituted."""


class Profile(BaseModel):
    """What you are, in the terms this board scores against."""

    name: str | None = None
    headline: str | None = Field(None, description="One-line self-description")
    years_experience: float | None = Field(
        None, description="Total professional years. Drives the experience half of every fit score."
    )
    location: str | None = Field(None, description="Current city, e.g. 'Bangalore, India'")
    skills: list[str] = Field(
        default_factory=list,
        description="As you would write them. jobcore's taxonomy normalises 'reactjs' to 'react' at scoring time, so exact spelling does not matter.",
    )
    titles: list[str] = Field(
        default_factory=list, description="Role titles you are targeting, used to bias ranking"
    )
    preferred_modes: list[str] = Field(
        default_factory=list, description="Any of Remote / Hybrid / Office. Empty means no preference."
    )
    min_pay_usd_year: int | None = Field(
        None, description="Floor on Uplers' USD/year normalisation. Roles below it are flagged, not hidden."
    )
    notice_period_days: int | None = Field(
        None,
        description="Days you need before joining. THE decisive field on this board - most Uplers clients accept only 15-30 days.",
    )
    avoid_companies: list[str] = Field(
        default_factory=list, description="End clients to exclude from ranking"
    )
    source: str | None = Field(None, description="Where this profile came from")
    updated_at: str | None = None

    def normalised_modes(self) -> list[str]:
        wanted = []
        for mode in self.preferred_modes:
            for known in MODES:
                if known.lower() == str(mode).strip().lower():
                    wanted.append(known)
        return wanted

    def is_usable(self) -> bool:
        """A profile with no skills and no experience cannot score anything."""
        return bool(self.skills) or self.years_experience is not None


# --- résumé parsing -------------------------------------------------------

_HEADING_RE = re.compile(r"^#{1,3}\s+(.+?)\s*$", re.MULTILINE)
_BOLD_RE = re.compile(r"\*\*(.+?)\*\*")
_YEARS_RE = re.compile(r"(\d+(?:\.\d+)?)\+?\s*years?\s+of\s+experience", re.IGNORECASE)
_CITY_RE = re.compile(r"^-\s*([A-Z][A-Za-z .]+,\s*[A-Z][A-Za-z ]+)\s*$", re.MULTILINE)
_SKILL_LINE_RE = re.compile(r"^-\s*(?:\*\*(.+?):\*\*)?\s*(.+?)\s*$", re.MULTILINE)

# Parenthesised qualifiers such as "AWS (S3, Lambda)" would otherwise split
# into a bogus "S3" skill and lose the "AWS" it qualifies.
_PAREN_RE = re.compile(r"\s*\(([^)]*)\)")


def _section(text: str, heading: str) -> str | None:
    """Return the body under a markdown heading, or None if absent."""
    matches = list(_HEADING_RE.finditer(text))
    for index, match in enumerate(matches):
        if match.group(1).strip().lower() == heading.strip().lower():
            start = match.end()
            end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
            return text[start:end]
    return None


def _split_skills(body: str) -> list[str]:
    """Pull individual skill names out of a 'Category: a, b, c' bullet list."""
    found: list[str] = []
    for match in _SKILL_LINE_RE.finditer(body):
        payload = match.group(2) or ""
        payload = _PAREN_RE.sub("", payload)  # "AWS (S3, Lambda)" -> "AWS"
        payload = payload.replace("**", "").strip()
        if ":" in payload and match.group(1) is None:
            payload = payload.split(":", 1)[1]
        for piece in re.split(r"[,/]", payload):
            skill = piece.strip(" .;")
            if skill and len(skill) <= 40 and not skill.lower().startswith("http"):
                if skill not in found:
                    found.append(skill)
    return found


def parse_resume_markdown(text: str) -> dict:
    """Extract seed profile fields from a résumé in markdown.

    Returns only the fields it could actually find. A missing section yields a
    missing key, never a guessed value - the caller decides what to do about
    an incomplete seed.
    """
    seed: dict = {}
    headings = _HEADING_RE.findall(text)
    if headings:
        seed["name"] = headings[0].strip().title()

    # The line right after the name carries the headline and usually the years.
    lead = text.split("\n\n", 2)
    intro = lead[1] if len(lead) > 1 else ""
    bold = _BOLD_RE.findall(intro)
    if bold:
        seed["headline"] = bold[0].strip()
        seed["titles"] = [bold[0].strip()]
    years = _YEARS_RE.search(intro) or _YEARS_RE.search(text)
    if years:
        seed["years_experience"] = float(years.group(1))

    contact = _section(text, "CONTACT DETAILS")
    if contact:
        city = _CITY_RE.search(contact)
        if city:
            seed["location"] = city.group(1).strip()

    skills_body = _section(text, "TECHNICAL SKILLS")
    if skills_body:
        skills = _split_skills(skills_body)
        if skills:
            seed["skills"] = skills

    return seed


def resume_path() -> Path | None:
    """The résumé to seed from, if one is configured and present."""
    candidate = Path(os.environ.get("UPLERS_RESUME", config.DEFAULT_RESUME_PATH))
    return candidate if candidate.is_file() else None


# --- persistence ----------------------------------------------------------


def profile_path() -> Path:
    return config.DATA_DIR / "profile.json"


def load(*, path: Path | None = None) -> Profile | None:
    """Read the stored profile, or None if it has never been set."""
    target = path or profile_path()
    if not target.is_file():
        return None
    try:
        with target.open(encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError) as exc:
        raise ProfileError(
            "%s exists but could not be read as JSON (%s). Fix or delete the file; "
            "this server will not silently fall back to a default profile, because "
            "every fit score would then be computed against somebody who is not you."
            % (target, exc)
        ) from exc
    return Profile(**data)


def save(profile: Profile, *, path: Path | None = None) -> Path:
    """Write the profile atomically, so a crash cannot leave a half file."""
    target = path or profile_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    profile.updated_at = ids.utcnow_iso()
    temp = target.with_suffix(".json.tmp")
    with temp.open("w", encoding="utf-8") as handle:
        json.dump(profile.model_dump(), handle, ensure_ascii=False, indent=2)
    os.replace(temp, target)
    return target


def seed_from_resume(*, resume: Path | None = None, path: Path | None = None) -> Profile:
    """Build and persist a profile from the résumé markdown.

    Raises rather than returning an empty profile when no résumé is available,
    because an empty profile scores every job identically and the scores would
    look real.
    """
    source = resume or resume_path()
    if source is None:
        raise ProfileError(
            "No profile is set and no résumé was found to seed one from (looked at %s, "
            "override with the UPLERS_RESUME environment variable). Call "
            "uplers_set_profile(skills=..., years_experience=..., ...) to create one."
            % config.DEFAULT_RESUME_PATH
        )
    text = source.read_text(encoding="utf-8", errors="replace")
    seed = parse_resume_markdown(text)
    if not seed.get("skills") and seed.get("years_experience") is None:
        raise ProfileError(
            "Read %s but found neither a TECHNICAL SKILLS section nor a years-of-experience "
            "line, so there is nothing to score against. Set the profile explicitly with "
            "uplers_set_profile()." % source
        )
    profile = Profile(**seed, source="resume:%s" % source.name)
    save(profile, path=path)
    return profile


def load_or_seed(*, path: Path | None = None) -> tuple[Profile, bool]:
    """The accessor every scoring tool uses. Returns (profile, was_seeded)."""
    existing = load(path=path)
    if existing is not None:
        return (existing, False)
    return (seed_from_resume(path=path), True)


def require(*, path: Path | None = None) -> Profile:
    """Load, seeding if needed, and refuse to return an unusable profile."""
    profile, _ = load_or_seed(path=path)
    if not profile.is_usable():
        raise ProfileError(
            "The stored profile has no skills and no years_experience, so a fit score "
            "would be meaningless. Set it with uplers_set_profile(skills=[...], "
            "years_experience=...)."
        )
    return profile
