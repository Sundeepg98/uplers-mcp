"""The two pre-apply assessment gates Uplers already ships on every row.

Every authenticated row this server fetches carries `ai_needed` and
`custom_screening_needed`, and until now nothing read them. No new endpoint was
added to get at them and none is needed: they arrive on
`GET talent/hr/opportunities` and `GET talent/hr/my-opportunities` alongside the
eighty-odd other fields those routes already return. This module is a pure
extraction layer over payloads that were already on the wire.

WHAT THESE FLAGS MEAN, AND WHAT THEY DO NOT
===========================================
They are PRE-APPLY signal. A true value says "this requisition will demand an
assessment before you can apply to it". They are NOT pipeline signal and they
do NOT explain why an application stalls after it is sent. That distinction is
the whole reason this docstring is long, because the numbers invite exactly the
wrong reading.

MEASURED, on the two captured fixtures, before a line of this module existed:

  * `tests/fixtures/talent_pipeline.json` - HIS REAL APPLICATIONS, all nine of
    them. `ai_needed` present on 9 of 9 rows, type `bool`, value `False` on
    every one. `custom_screening_needed`, identically: 9 of 9, `bool`, all
    `False`.
  * `tests/fixtures/talent_feed.json` - 3 rows. Both flags present on 3 of 3,
    type `bool`, value `False` on every one.

So a reader who sees "zero gated" in his pipeline summary and concludes the
pipeline is healthy has drawn the opposite of the truth. All nine of his
applications read `ai_needed: false` because that flag describes the
REQUISITION he applied to, not the state of his application. The real shape of
the assessment obstacle is elsewhere and it is large: 99 of the 250 records in
the local index carry a non-empty assessments array (40% of the reachable work
is gated behind an AiInterview or a TestGorilla test), and his own cleared
counter reads `0` - see `tests/fixtures/talent_assessments.json`, which is the
literal envelope `{"status": 200, "data": {..., "cleared": 0}}`. Forty percent
of the board demands a test he has never sat. That is the finding. A low count
out of these two flags is not evidence against it.

The corroboration is on the same nine rows. `custom_screening_needed` is
`False` on all nine, yet the neighbouring `is_custome_screening` (Uplers' own
spelling) reads `True` on TWO of them, each with a real `custom_screening_at`
timestamp - `2026-08-12 02:58:26` and `2026-05-26 21:24:52`. The `*_needed`
field and the `is_*` field are therefore not the same fact: one is the demand a
requisition makes up front, the other records what actually happened to that
application. Reading either as the other is the mistake this module exists to
make hard. Those neighbouring fields are deliberately NOT extracted here.

WHERE THE FLAGS LIVE
====================
Depth one on the row, on both surfaces. Both envelopes are Laravel paginators
whose rows sit at `payload["hrs"]["data"]`, and the flags are plain top-level
keys of each row. On `my-opportunities` the row is the APPLICATION and the
requisition is nested at `row["hr"]`; that nested object was checked on all
nine rows and carries NEITHER flag. So `record.get("ai_needed")` is correct for
both surfaces and no nesting logic is warranted.

WHY THE TYPES ARE NORMALISED ANYWAY
===================================
Both flags measured as real JSON booleans in all 24 observations, so on today's
evidence normalisation is doing nothing. It is here because this API is
demonstrably inconsistent about types elsewhere: it returns decimal STRINGS
like "5.00" for numbers, uses integer `200` on one route and the string
"success" on another for the same status field, and puts a date string in a
field named `is_partner_company`. On these very rows, `ai_mandatory` is the
integer `0` on all three feed rows and is ABSENT from all nine pipeline rows -
the same field, two surfaces, present-as-int against missing. A reader that
assumed `bool` would break on the first row that drifted, and a reader that
used plain truthiness would read the string "false" as True.

ABSENT IS NOT FALSE
===================
A row that never carried the field is not a row that carried `false`, and
collapsing the two produces a count that is confidently wrong. `extract_flags`
returns `None` for a flag it cannot read, never `False`. `summarise_flags`
keeps four buckets that sum exactly to the row count:

    true           the value read as true
    false          the value read as false
    unknown        the key was absent, or null, or an empty string - the API
                   did not state a value
    unrecognised   the API stated something that is not readable as a boolean,
                   such as a date string or a dict. The raw value is reported
                   in `unrecognised_values` rather than being guessed at.

NEITHER FIXTURE CAN EXERCISE the unknown, unrecognised or true paths for these
two fields: all 24 observations are a present `bool` `False`. Those paths are
covered by small synthetic rows in `tests/test_assessment_flags.py`, and that
file says so rather than pretending the capture proved something it did not.
"""

from __future__ import annotations


# The two fields. Spelled exactly as the API spells them on both surfaces.
FLAGS = ("ai_needed", "custom_screening_needed")

# The four-way reading of one field on one row. Deliberately four and not the
# tri-state bool `extract_flags` returns, because "the API said nothing" and
# "the API said something unreadable" are different problems: the first is
# normal, the second is drift and should be visible.
STATE_TRUE = "true"
STATE_FALSE = "false"
STATE_UNKNOWN = "unknown"
STATE_UNRECOGNISED = "unrecognised"

STATES = (STATE_TRUE, STATE_FALSE, STATE_UNKNOWN, STATE_UNRECOGNISED)

# String spellings accepted for each boolean. Compared lowercased and stripped.
# Anything outside these sets that is not numeric is UNRECOGNISED rather than
# truthy - `bool("false")` is True in Python and that is precisely the bug.
TRUE_TOKENS = frozenset(("1", "t", "true", "y", "yes"))
FALSE_TOKENS = frozenset(("0", "f", "false", "n", "no"))


def _classify_present(value) -> str:
    """Read one value that the row actually carried. Never guesses.

    `bool` is tested before `int` because in Python `bool` IS an `int`
    subclass, and getting that order wrong would report every `True` through
    the integer path.
    """
    if value is None:
        # JSON null. The key was there; the value was not.
        return STATE_UNKNOWN
    if isinstance(value, bool):
        return STATE_TRUE if value else STATE_FALSE
    if isinstance(value, (int, float)):
        if value == 1:
            return STATE_TRUE
        if value == 0:
            return STATE_FALSE
        # A 2, a 7, a NaN. Numeric, but not a boolean anyone can defend.
        return STATE_UNRECOGNISED
    if isinstance(value, str):
        token = value.strip().lower()
        if token == "":
            return STATE_UNKNOWN
        if token in TRUE_TOKENS:
            return STATE_TRUE
        if token in FALSE_TOKENS:
            return STATE_FALSE
        try:
            number = float(token)
        except ValueError:
            # A date string, a sentence, anything else. This is the
            # `is_partner_company` disease and it must not read as True.
            return STATE_UNRECOGNISED
        if number == 1:
            return STATE_TRUE
        if number == 0:
            return STATE_FALSE
        return STATE_UNRECOGNISED
    # dict, list, and everything else.
    return STATE_UNRECOGNISED


def read_flag(record: dict, field: str) -> str:
    """One flag on one row, as one of `STATES`.

    The shared classifier behind both public functions. Exposed because the
    four-way state carries strictly more than the tri-state bool - it separates
    "not stated" from "stated unreadably" - not because `server.py` needs it.
    `extract_flags` and `summarise_flags` are the contract.
    """
    if not isinstance(record, dict):
        raise TypeError(
            "read_flag needs one row dict, got %s. The rows of both talent "
            "surfaces are at payload['hrs']['data']."
            % type(record).__name__
        )
    if field not in record:
        return STATE_UNKNOWN
    return _classify_present(record[field])


def _to_bool(state: str):
    """One of `STATES` down to the tri-state bool. Absent stays absent."""
    if state == STATE_TRUE:
        return True
    if state == STATE_FALSE:
        return False
    return None


def extract_flags(record: dict) -> dict:
    """The two assessment flags off ONE row, normalised to real booleans.

    Returns exactly two keys, `ai_needed` and `custom_screening_needed`, each
    `True`, `False`, or `None`. `None` means the row did not state a readable
    value - the key was absent, or null, or empty, or held something no one can
    read as a boolean. It NEVER means false. A caller that treats `None` as
    false is inventing a fact the API did not supply; use `summarise_flags` or
    `read_flag` if the difference matters.

    THIS IS PRE-APPLY SIGNAL, NOT PIPELINE SIGNAL. A true value means the
    requisition will demand an assessment BEFORE an application can be sent. It
    says nothing about an application already in flight, and a false value is
    not evidence that a stalled application is healthy. MEASURED: all nine of
    his real applications in `tests/fixtures/talent_pipeline.json` read
    `ai_needed: false` and `custom_screening_needed: false`, and all three rows
    of `tests/fixtures/talent_feed.json` do too - 24 observations, every one a
    JSON `bool` `False`, none absent. Meanwhile 99 of the 250 requisitions on
    the board demand an assessment and his cleared counter reads 0
    (`tests/fixtures/talent_assessments.json`). Zero gated rows here is a fact
    about these rows, not a clean bill of health.

    Works unchanged on both surfaces: the flags are top-level keys of the row
    on `talent/hr/opportunities` and on `talent/hr/my-opportunities` alike, and
    the pipeline row's nested `row["hr"]` requisition carries neither.
    """
    return {field: _to_bool(read_flag(record, field)) for field in FLAGS}


def summarise_flags(records: list) -> dict:
    """Count both assessment flags across many rows. Pure; no I/O, no clock.

    Takes the ROW LIST - `payload["hrs"]["data"]` on both talent surfaces - and
    returns:

        {
          "rows": int,                     how many rows were read
          "gated": int,                    rows where EITHER flag read true,
                                           i.e. rows that will demand an
                                           assessment before he can apply
          "flags": {
            "ai_needed":               {"true": n, "false": n,
                                        "unknown": n, "unrecognised": n},
            "custom_screening_needed": {... the same four ...},
          },
          "unrecognised_values": [         deduped, so a drifted field on 250
            {"field": str,                 rows reports once with rows=250
             "value": str,                 repr of the raw value
             "rows": int},
          ],
        }

    Each flag's four counts sum to `rows` exactly. `unknown` and `false` are
    separate buckets on purpose: a field the API never sent is not a field the
    API set to false, and adding them together yields a confident lie.

    THE COUNTS ARE PRE-APPLY DEMAND, NOT PIPELINE HEALTH. `gated` counts
    requisitions that will require an assessment to apply. It does not count
    applications blocked by an assessment, and a `gated` of 0 must never be
    reported as evidence that his pipeline is moving. MEASURED on the captured
    fixtures: `talent_pipeline.json` (his nine real applications) summarises to
    `gated: 0` with `false: 9` on both flags, and `talent_feed.json` to
    `gated: 0` with `false: 3`. The assessment obstacle is real regardless - 99
    of 250 board requisitions demand one and he has cleared 0 - it simply is
    not what these two fields measure.

    Raises `TypeError` on the envelope or on a non-dict row rather than
    returning a zeroed summary, because a summary of nothing and a summary of
    zero look identical downstream.
    """
    if isinstance(records, dict):
        raise TypeError(
            "summarise_flags takes the ROW LIST, not the envelope. Both "
            "talent surfaces nest it at payload['hrs']['data']."
        )

    counts = {field: dict.fromkeys(STATES, 0) for field in FLAGS}
    unrecognised = {}
    rows = 0
    gated = 0

    for index, record in enumerate(records):
        if not isinstance(record, dict):
            raise TypeError(
                "Row %d is %s, not a dict. summarise_flags takes the row list "
                "at payload['hrs']['data']." % (index, type(record).__name__)
            )
        rows += 1
        row_is_gated = False
        for field in FLAGS:
            state = read_flag(record, field)
            counts[field][state] += 1
            if state == STATE_TRUE:
                row_is_gated = True
            elif state == STATE_UNRECOGNISED:
                key = (field, repr(record[field]))
                unrecognised[key] = unrecognised.get(key, 0) + 1
        if row_is_gated:
            gated += 1

    return {
        "rows": rows,
        "gated": gated,
        "flags": counts,
        "unrecognised_values": [
            {"field": field, "value": value, "rows": seen}
            for (field, value), seen in sorted(unrecognised.items())
        ],
    }
