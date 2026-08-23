"""Query parameters for Uplers' OWN saved-jobs list, and the guard on them.

Two saved-jobs lists exist and they are disjoint. `uplers_save_job` is a
purely LOCAL shortlist held in this server's database. The list this module
reads is the SERVER-SIDE one - his bookmarks on platform.uplers.com. Neither
can see the other, and nothing here changes that; this module only builds the
read.

WHY A WHOLE MODULE FOR FOUR QUERY PARAMETERS
--------------------------------------------
Because the parameter is a trap that answers 200 instead of erroring. Both
facts below are VERIFIED in Uplers' production bundle chunk 8562 - the builder
the live jobs board actually uses, NOT chunk 2893, which the 2026-08-21 audit
read and which never emits this parameter at all. They are recorded verbatim
at `endpoints.QP_IS_SAVED_FILTER`, which is the specification this module
implements.

  1.  **It is the integer 1, never the boolean true.** Their test is
      ``1===t.is_saved_filter``, which is strict. A JSON ``true`` or the
      string ``"true"`` is a different request, and Python makes this
      especially easy to get wrong because ``True == 1`` is itself true - so
      an equality assertion cannot tell the two apart. See
      `assert_integer_one`, which is the check that can.

  2.  **It is EXCLUSIVE.** Their code is
      ``1===t.is_saved_filter ? <saved branch> : Object.keys(t).map(...)``.
      The saved branch REPLACES the loop that turns every other key into a
      query parameter, so `roles`, `locations`, `experience`, `engagements`
      and anything else are all DROPPED. Only `search` is emitted inside the
      saved branch. `pagination`, `page`, `is_count` and `activeJob` sit
      OUTSIDE the ternary and are sent either way.

The consequence is the reason for the refusal below. Asking for "my saved
Node.js jobs in Bangalore" would return his saved jobs UNFILTERED, and the
caller would present that list as filtered. A silently wrong answer is worse
than an error, so this builder REFUSES the combination rather than quietly
dropping what the server would drop.

The rejection rule is DENY BY DEFAULT, not a blocklist. Their branch emits
`search` and nothing else, so every name this module has not measured as
surviving is treated as dropped. An enumerated blocklist would let a filter
Uplers adds next month through in silence, which is the exact failure this
module exists to prevent.

WHAT THIS MODULE DELIBERATELY DOES NOT SEND
-------------------------------------------
`is_count` and `activeJob`. They are outside the ternary and their client does
send them, but their VALUES were never captured, and a guessed value is a
different request. They are named in `OUTSIDE_TERNARY` so a caller that knows
a real value can pass it through, and they are recorded here as a known gap
rather than filled in.

THE RESPONSE
------------
`read_saved_page` shapes it. Measured against
`tests/fixtures/saved_filter_page.json`, captured live on 2026-08-23:
``bookmarkedCount`` is **0** and ``hrs.data`` is **[]**. He has zero jobs
saved on the platform today. That is an honest answer, not a failure, and the
shaper renders it as a sentence rather than as an empty result that reads like
a broken read.

That same capture also fixes what the paginator does NOT carry: there is no
``total`` and no ``last_page``. The keys present are ``current_page``,
``data``, ``first_page_url``, ``from``, ``next_page_url``, ``path``,
``per_page``, ``prev_page_url`` and ``to``. "Is there another page" is
therefore answerable only from ``next_page_url``, and a total count of saved
jobs is not answerable at all beyond ``bookmarkedCount``.
"""

from __future__ import annotations

from typing import Any

from .endpoints import QP_IS_SAVED_FILTER

#: The value, as an integer. Their comparison is ``1===t.is_saved_filter``.
#: Written as a named constant so that no call site ever types a bare literal
#: that a linter or a refactor could helpfully "simplify" into True.
SAVED_FILTER_ON = 1

#: The only filter their saved branch emits alongside the flag.
COMPATIBLE_FILTERS = frozenset({"search"})

#: Sent either way, because they sit outside the ternary. Passing one of these
#: is not an error - the server really does receive it.
OUTSIDE_TERNARY = frozenset({"pagination", "page", "is_count", "activeJob"})

#: Named in the refusal message because they are the ones a caller is most
#: likely to reach for. NOT the definition of what is rejected - that is deny
#: by default, see `rejected_filters`.
KNOWN_DROPPED = ("roles", "locations", "experience", "engagements")

_ALLOWED = COMPATIBLE_FILTERS | OUTSIDE_TERNARY | {QP_IS_SAVED_FILTER}


class SavedFilterRefused(ValueError):
    """A saved-jobs request was stopped before it was built.

    Distinct from a failure: nothing was attempted and nothing was sent. The
    message names which parameter would have been silently discarded, because
    the whole point is that the server would not have complained.
    """

    kind = "saved_filter_refused"


def rejected_filters(requested: dict) -> list[str]:
    """The names in `requested` that the saved branch would silently ignore.

    Deny by default: anything outside `COMPATIBLE_FILTERS`, `OUTSIDE_TERNARY`
    and the flag itself is reported. Input order is preserved so the message
    reads back in the order the caller wrote them.

    Returns [] for a request the server would honour in full, which is what
    makes this usable as a guard rather than as a blanket refusal.
    """
    if not isinstance(requested, dict):
        return []
    return [name for name in requested if name not in _ALLOWED]


def saved_jobs_params(
    *,
    search: str | None = None,
    page: int = 1,
    pagination: int = 20,
    **filters: Any,
) -> dict:
    """Query parameters for the platform-side saved-jobs read.

    `search` rides alongside the flag and is the ONLY filter that does. It is
    omitted entirely when blank, because the live response echoes ``search``
    as ``""`` and sending an empty needle is not a search.

    `**filters` exists so the guard is reachable. A name in `OUTSIDE_TERNARY`
    is passed through unchanged; anything else raises `SavedFilterRefused`
    naming it, instead of Python's own "unexpected keyword argument", which
    would say nothing about why the combination is meaningless.

    Raises:
        SavedFilterRefused: a filter was supplied that the saved branch drops,
            or `page` / `pagination` was not a positive integer.
    """
    ignored = rejected_filters(filters)
    if ignored:
        raise SavedFilterRefused(
            "The saved-jobs view IGNORES %s. Uplers' own code short-circuits every "
            "other filter when is_saved_filter is 1 (only %s survives), so the request "
            "would have come back as your saved jobs UNFILTERED and looked filtered. "
            "Nothing was sent. Read the saved list first, then filter it here."
            % (", ".join(ignored), ", ".join(sorted(COMPATIBLE_FILTERS)))
        )

    params: dict[str, Any] = {
        QP_IS_SAVED_FILTER: SAVED_FILTER_ON,
        "page": _positive("page", page),
        "pagination": _positive("pagination", pagination),
    }
    if isinstance(search, str) and search.strip():
        params["search"] = search.strip()
    for name, value in filters.items():
        params[name] = value
    return params


def assert_integer_one(params: dict) -> None:
    """Raise unless the flag is the INTEGER 1.

    Exists because ``params[QP_IS_SAVED_FILTER] == 1`` is satisfied by
    ``True``, so the obvious assertion is one that cannot fail on the one
    input it was written to catch. ``type(...) is int`` is False for a bool -
    bool subclasses int, so `isinstance` would not discriminate either.
    """
    value = params.get(QP_IS_SAVED_FILTER)
    if type(value) is not int or value != SAVED_FILTER_ON:
        raise AssertionError(
            "%s must be the integer %d, got %r (%s). Uplers compares with ===, so a "
            "boolean or a string is a different request."
            % (QP_IS_SAVED_FILTER, SAVED_FILTER_ON, value, type(value).__name__)
        )


def read_saved_page(payload: Any) -> dict:
    """Shape one `is_saved_filter=1` response.

    Every key below is read from a field measured present in
    `tests/fixtures/saved_filter_page.json`. Two absences are load-bearing:

      * there is no ``total`` and no ``last_page``, so `total_pages_known` is
        False and `has_more` is derived from ``next_page_url`` alone;
      * ``from`` and ``to`` are null on an empty page, so the returned count
        comes from ``len(data)`` rather than from that arithmetic.

    ``per_page`` arrives as the STRING "20" and is coerced, which is the kind
    of thing that turns a page-size comparison into a silent False.
    """
    body = payload if isinstance(payload, dict) else {}
    hrs = body.get("hrs") if isinstance(body.get("hrs"), dict) else {}
    rows = hrs.get("data")
    jobs = list(rows) if isinstance(rows, list) else []
    next_url = hrs.get("next_page_url")

    return {
        "bookmarked_count": _int_or_none(body.get("bookmarkedCount")),
        "jobs": jobs,
        "returned": len(jobs),
        "page": _int_or_none(hrs.get("current_page")),
        "per_page": _int_or_none(hrs.get("per_page")),
        "has_more": bool(next_url),
        "next_page_url": next_url if isinstance(next_url, str) else None,
        "search": body.get("search") if isinstance(body.get("search"), str) else "",
        "total_pages_known": False,
        "summary": _summary(_int_or_none(body.get("bookmarkedCount")), len(jobs)),
    }


# --- internals -------------------------------------------------------------


def _summary(bookmarked: int | None, returned: int) -> str:
    """The zero case is an ANSWER. It is the live one as of 2026-08-23."""
    if returned == 0 and not bookmarked:
        return (
            "You have no jobs saved on the Uplers platform. That is Uplers' own "
            "bookmark list, which is separate from this server's local shortlist - "
            "uplers_list_saved() reads the local one."
        )
    if bookmarked is None:
        return "%d saved job(s) on this page." % returned
    return "%d saved job(s) on this page, %d bookmarked in total." % (returned, bookmarked)


def _positive(name: str, value: Any) -> int:
    if type(value) is not int or value < 1:
        raise SavedFilterRefused(
            "%s must be a positive integer, got %r. Nothing was sent." % (name, value)
        )
    return value


def _int_or_none(value: Any) -> int | None:
    """Their paginator writes `per_page` as a string and the rest as ints."""
    if type(value) is int:
        return value
    if isinstance(value, str) and value.strip().lstrip("-").isdigit():
        return int(value.strip())
    return None
