"""HR-number parsing.

Uplers requisition ids are the string "HR" followed by digits, and the digit
count is what separates the two populations on the board:

    HR030826155648      12 digits -> NATIVE, a real Uplers requisition.
                                     The digits are DDMMYYHHMMSS of creation.
    HR1173448373079993  16 digits -> AGGREGATED, a posting scraped from
                                     elsewhere and republished. ~99.4% of the
                                     sitemap. Noise for this server's purpose.

Length is a *heuristic* used when only the id is known (sitemap sync). The
authoritative signal is the record's own `is_aggregator_job` field, which
store.py records once a job has actually been fetched.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone

NATIVE_DIGITS = 12
AGGREGATED_DIGITS = 16

KIND_NATIVE = "native"
KIND_AGGREGATED = "aggregated"
KIND_UNKNOWN = "unknown"

_HR_RE = re.compile(r"^HR(\d+)$")


def normalise(hr_number: str) -> str:
    """Upper-case and strip an HR number. Does not validate."""
    return (hr_number or "").strip().upper()


def digits(hr_number: str) -> str | None:
    """Return the digit part of an HR number, or None if it is not one."""
    match = _HR_RE.match(normalise(hr_number))
    return match.group(1) if match else None


def is_valid(hr_number: str) -> bool:
    return digits(hr_number) is not None


def classify(hr_number: str) -> str:
    """Guess native/aggregated from the id alone.

    Anything that is neither 12 nor 16 digits is "unknown" rather than being
    forced into a bucket. The live board contains exactly one such id
    (HR0191124125506, 13 digits), so the case is real, not hypothetical.
    """
    d = digits(hr_number)
    if d is None:
        return KIND_UNKNOWN
    if len(d) == NATIVE_DIGITS:
        return KIND_NATIVE
    if len(d) == AGGREGATED_DIGITS:
        return KIND_AGGREGATED
    return KIND_UNKNOWN


def decode_created_at(hr_number: str) -> datetime | None:
    """Decode a 12-digit native id into its creation timestamp (UTC-naive).

    Returns None for aggregated ids, malformed ids, and 12-digit ids whose
    digits do not form a real date/time. Never raises.
    """
    d = digits(hr_number)
    if d is None or len(d) != NATIVE_DIGITS:
        return None
    try:
        day, month, year = int(d[0:2]), int(d[2:4]), int(d[4:6])
        hour, minute, second = int(d[6:8]), int(d[8:10]), int(d[10:12])
        return datetime(2000 + year, month, day, hour, minute, second)
    except ValueError:
        return None


def created_at_iso(hr_number: str) -> str | None:
    dt = decode_created_at(hr_number)
    return dt.isoformat() if dt else None


def extract_from_text(text: str) -> list[str]:
    """Pull every distinct HR id out of a blob of text, in first-seen order.

    Used on sitemap.xml, which is one 4.8 MB line.
    """
    seen: dict[str, None] = {}
    for match in re.finditer(r"HR\d+", text):
        seen.setdefault(match.group(0), None)
    return list(seen)


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0, tzinfo=None).isoformat()
