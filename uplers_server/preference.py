"""What Uplers thinks he wants, resolved from ids into words.

`GET talent/get-preference` is a plain read. VERIFIED LIVE: a real 200 with
real data was captured on 2026-08-23 by `scripts/capture_outreach.py` into
`tests/fixtures/talent_preference.json`, so the route is a measurement, not a
guess.

NOT the nurture route. An earlier pass through the bundle conflated two
constants and read `fJ7` - the NURTURE-preference route - as this one. They
are different endpoints with different payloads. Nothing in this module is
named nurture and nothing here calls it.

WHY IT IS WORTH READING
-----------------------
This server scores an opportunity against OUR profile. Uplers ranks him
against THEIRS, and until this route was read that ranking was invisible from
here. Surfacing his stored preference lets the two be compared - if Uplers
believes he is "Remote Only" and our profile says otherwise, that difference
explains feed contents that would otherwise look arbitrary.

THE SHAPE, AND WHERE THE BUG LIVES
----------------------------------
Top level is ``{talent, masters, snooze}``. `talent` stores IDS. `masters` is
eleven LOOKUP TABLES that map those ids to labels. A shaper that returns the
raw ids is useless, so the real work is the join - and the join is where this
repo has been bitten before (`talent_shape.MASTERS_KEY` records the day a
61-skill profile was reported as 0 because the join was skipped).

Two measured facts about that join, both of which break a naive
implementation:

  1.  **A master is not ordered by its own id.** `jobSearchPreferenceMaster`
      is ``[{1: Actively Looking}, {3: Passively Looking}, {2: Not looking}]``
      - index 1 holds value 3. A resolver that returned ``rows[0]``, or that
      indexed by position, would answer plausibly and wrongly. His stored
      `preferred_method` is "2", whose row is at index 1, and his
      `target_company_types` is "6", whose row is index 5; both are checked in
      the tests precisely because index 0 is a different, credible-looking
      answer.

  2.  **`cities` keys its numeric id under `id`, not `value`.** Ten of the
      eleven masters are ``{"label", "value"}`` with `value` carrying the id.
      `cities` is ``{"id": 277, "label": "Bengaluru", "value": "Bengaluru"}``
      - `value` is the NAME. Indexing every master by `value` (which is what
      `talent_shape.masters_index` does, correctly, for the profile payload's
      masters) resolves nothing for his city here. `_master_lookup` prefers
      `id` when a row carries one.

Ids are compared as strings on both sides. The payload disagrees with itself
about type - `job_search_preference` is the integer 1 while `preferred_method`
is the string "2" and `company_type` is the string "6" - so one ``str()`` on
each side removes the whole class of near-miss.

UNRESOLVED IS REPORTED, NEVER GUESSED
-------------------------------------
An id with no row in its master comes back with ``label == UNRESOLVED`` and
``resolved == False``, and is listed again in the top-level ``unresolved``
roll-up. It is never None (which reads as "not set") and never a fabricated
label. Two real cases in the live capture:

  * ``preferred_modes`` is ``[1, 3]`` and this payload ships NO master for it.
    Cross-reference, recorded because it is genuinely useful and NOT acted on:
    the `talent/profile` payload carries the same two ids as
    ``[{"value": 1, "label": "Full time"}, {"value": 3, "label": "Contract"}]``
    - engagement type, not work mode. That mapping is not imported here,
    because it comes from a different response and this one cannot prove it.
    See `talent_shape._work_mode_preference` for why conflating Uplers'
    `preferred_modes` with a Remote/Hybrid/Office field corrupts mode filters.

  * ``user_journey_status.sub_statuses`` carries bare ids with no named
    master. HYPOTHESIS, NOT VERIFIED: his status is 2 ("actively_applying")
    and `activelyApplyingJobBoardsMaster` exists in the same payload, so the
    sub-status master is plausibly selected BY the status. Testing it needs a
    second capture taken while his journey status is something else. Until
    then the ids are reported unresolved rather than joined to a guess.

PRIVACY
-------
The fixture was captured with pay and contact fields already deleted
(`current_ctc`, `expected_ctc`, `monthly_salary`, `ctc_breakdown`, resume and
profile URLs). This shaper does not look for them and emits no key matching
pay or contact, which the tests assert over the whole shaped tree. `snooze` is
reported as a COUNT only: the live list is empty, so its row shape is unknown,
and passing unknown rows through would be a hole in exactly that guarantee.
"""

from __future__ import annotations

from typing import Any

#: The marker a caller sees instead of a label when an id had no master row.
#: A visible sentinel rather than None, because None reads as "he did not set
#: this" - a different and much less alarming claim than "we could not resolve
#: what he did set".
UNRESOLVED = "UNRESOLVED"

#: Present in the payload but deliberately not emitted. `status_text` is a
#: static pipeline enum, not his state, and printing it beside his preferences
#: would read as a list of statuses he holds. The identity keys are not
#: preference and are not needed to compare two profiles.
NOT_PREFERENCE = ("status_text", "enc_id", "enc_id_nda", "enc_id_org", "name_extration")


def master_index(payload: Any) -> dict[str, dict[str, str]]:
    """`{master_name: {id_as_str: label}}` for every master in the payload."""
    masters = payload.get("masters") if isinstance(payload, dict) else None
    if not isinstance(masters, dict):
        return {}
    index: dict[str, dict[str, str]] = {}
    for name, rows in masters.items():
        lookup = _master_lookup(rows)
        if lookup:
            index[name] = lookup
    return index


def shape_preference(payload: dict) -> dict:
    """His stored Uplers preference, ids resolved to labels. Pure.

    No I/O, no network, no clock. Every emitted field traces to a field
    measured present in `tests/fixtures/talent_preference.json`.
    """
    body = payload if isinstance(payload, dict) else {}
    talent = body.get("talent") if isinstance(body.get("talent"), dict) else {}
    index = master_index(body)
    journey = talent.get("user_journey_status")
    journey = journey if isinstance(journey, dict) else {}

    shaped: dict[str, Any] = {
        "job_search_preference": resolve(
            "jobSearchPreferenceMaster", talent.get("job_search_preference"), index
        ),
        "job_search_unavailable_until": _text(talent.get("job_search_unavailable_until")),
        "user_journey_status": resolve(
            "userJourneyStatusMaster", journey.get("status"), index
        ),
        "user_journey_sub_statuses": [
            resolve(None, row.get("sub_status") if isinstance(row, dict) else row, index)
            for row in _rows(journey.get("sub_statuses"))
        ],
        "applications_per_day": journey.get("applications_per_day"),
        "interviews_per_week": journey.get("interviews_per_week"),
        "preferred_method": resolve(
            "preferredMethodMaster", _single(talent.get("preferred_method"), "preferred_method"), index
        ),
        "preferred_modes": [
            resolve(None, row, index) for row in _rows(talent.get("preferred_modes"))
        ],
        "target_company_types": [
            resolve(
                "preferredCompanyTypesMaster",
                row.get("company_type") if isinstance(row, dict) else row,
                index,
                given_label=row.get("company_type_text") if isinstance(row, dict) else None,
            )
            for row in _rows(talent.get("target_company_types"))
        ],
        "preferred_cities": [
            resolve(
                "cities",
                row.get("value") if isinstance(row, dict) else row,
                index,
                given_label=row.get("label") if isinstance(row, dict) else None,
            )
            for row in _rows(talent.get("preferred_cities"))
        ],
        "current_location": _location(talent.get("current_location"), index),
        "availability": resolve("availabilityMaster", talent.get("availability"), index),
        "joining_period": resolve("joiningMaster", talent.get("joining_period"), index),
        "serving_notice_period": _text(talent.get("serving_notice_period")),
        "last_working_day": _text(talent.get("last_working_day")),
        "job_title": _text(talent.get("job_title")),
        "total_experience": _text(talent.get("total_experience")),
        "total_experience_years": _float_or_none(talent.get("total_experience")),
        "interested_job_functions": _job_functions(talent.get("interested_job_functions")),
        "top_skills": _skill_names(talent.get("talent_top_skills")),
        "snooze_count": len(_rows(body.get("snooze"))),
        "masters_present": sorted(index),
    }
    shaped["unresolved"] = _unresolved_roll_up(shaped)
    return shaped


def resolve(
    master: str | None,
    raw: Any,
    index: dict[str, dict[str, str]],
    given_label: Any = None,
) -> dict | None:
    """One id joined to its master row. None when nothing was set.

    The join is a dict lookup keyed by the id as a string. It SELECTS the
    matching row; it never falls back to a position, which is the failure this
    whole module is shaped around - see the module docstring, fact 1.

    `master=None` means "this payload ships no master for that field". The
    entry still comes back, carrying the id and `UNRESOLVED`, so the caller
    sees an id it cannot name rather than a field that vanished.
    """
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        return None
    identifier = str(raw).strip()
    label = (index.get(master) or {}).get(identifier) if master else None
    return {
        "id": identifier,
        "label": label if label is not None else UNRESOLVED,
        "resolved": label is not None,
        "master": master,
        "given_label": _text(given_label),
    }


# --- internals -------------------------------------------------------------


def _master_lookup(rows: Any) -> dict[str, str]:
    """`{id_as_str: label}` for one master table.

    `id` wins over `value` when a row carries both. Measured: only `cities`
    does, and there `value` holds the city NAME while `id` holds the 277-style
    key his `preferred_cities` and `current_location` actually reference.
    Indexing that table by `value` yields a name-to-name map that resolves
    none of his stored ids.
    """
    lookup: dict[str, str] = {}
    for row in _rows(rows):
        if not isinstance(row, dict):
            continue
        label = row.get("label")
        if label in (None, ""):
            continue
        key = row.get("id") if row.get("id") is not None else row.get("value")
        if key is None:
            continue
        lookup[str(key)] = str(label)
    return lookup


def _location(raw: Any, index: dict[str, dict[str, str]]) -> dict | None:
    """`current_location` is `{"label": ..., "value": <city id>}`.

    Its inline label and the master's disagree in a small, harmless way - the
    record says "Bengaluru, Karnataka" and `cities` says "Bengaluru" - so both
    are carried: `label` is always the master's answer, `given_label` is what
    the record itself wrote.
    """
    if isinstance(raw, dict):
        return resolve("cities", raw.get("value"), index, given_label=raw.get("label"))
    return resolve("cities", raw, index)


def _job_functions(rows: Any) -> list[dict]:
    """Names are INLINE here - `job_function.name` - so no master is needed."""
    out: list[dict] = []
    for row in _rows(rows):
        if not isinstance(row, dict):
            continue
        function = row.get("job_function")
        function = function if isinstance(function, dict) else {}
        name = _text(function.get("name"))
        if name is None:
            continue
        out.append(
            {
                "id": str(row.get("job_function_id")) if row.get("job_function_id") is not None else None,
                "name": name,
                "category": _text(function.get("category")),
            }
        )
    return out


def _skill_names(rows: Any) -> list[str]:
    """`talent_top_skills[].skill.name`, in Uplers' own order.

    Names only. The nested skill record also carries an image URL and audit
    timestamps, none of which is preference.
    """
    out: list[str] = []
    for row in _rows(rows):
        if not isinstance(row, dict):
            continue
        skill = row.get("skill")
        name = _text(skill.get("name")) if isinstance(skill, dict) else None
        if name is not None and name not in out:
            out.append(name)
    return out


def _unresolved_roll_up(shaped: dict) -> list[str]:
    """Every id that could not be named, as `master:id`.

    Reported rather than dropped, which is the standing law in this package -
    an invisible gap is how the 0-skills bug survived hundreds of tests.
    """
    found: list[str] = []

    def visit(value: Any) -> None:
        if isinstance(value, dict):
            if value.get("resolved") is False and "id" in value:
                entry = "%s:%s" % (value.get("master") or "<no master in payload>", value["id"])
                if entry not in found:
                    found.append(entry)
                return
            for item in value.values():
                visit(item)
        elif isinstance(value, list):
            for item in value:
                visit(item)

    visit(shaped)
    return found


def _single(raw: Any, key: str) -> Any:
    """`preferred_method` arrives as `[{"preferred_method": "2"}]`. Unwrap it."""
    if isinstance(raw, list):
        raw = raw[0] if raw else None
    if isinstance(raw, dict):
        for candidate in (key, "value", "id"):
            if raw.get(candidate) is not None:
                return raw[candidate]
        return None
    return raw


def _rows(value: Any) -> list:
    return list(value) if isinstance(value, (list, tuple)) else []


def _text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _float_or_none(value: Any) -> float | None:
    """`total_experience` is the STRING "5.2" on the live record."""
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return None
