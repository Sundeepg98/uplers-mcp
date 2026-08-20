"""An ABSOLUTE ceiling on the daily brief, not another relative bound.

The README quotes a character count for `uplers_daily_brief`. Until now no
test pinned it: the two token-economy checks in test_tier2.py assert only
relative bounds (a row under 600 chars, ten rows cheaper than two raw
records), so the documented figure could drift arbitrarily far from reality
without anything going red - and it had. A number that reads as measured but
is not reproducible is worse than no number, so this file makes it both.

Measured against the FIXTURE cohort, not the live index, because the live
number is not a constant: `since` defaults to the last brief (seven days on a
first run), so the size tracks how many requisitions landed in the window. On
the real 235-record index on 2026-08-20 the same call ranged from 509 chars
(empty one-day window) to 4,206 (limit=10 over a week). The README says so.
"""

from __future__ import annotations

import pytest

from uplers_server import ids
from uplers_server.models import DailyBrief

from conftest import NATIVE_IDS, put_fixtures

pytestmark = pytest.mark.asyncio


# The call below measures 1,686 chars on this cohort (2026-08-20). The ceiling
# is that plus ~19%: enough headroom that a wording tweak does not go red,
# little enough that a shape regression does. One URL per row - the single
# largest avoidable cost the README names - would add ~180 chars a row and
# blow straight through it.
BRIEF_CEILING_CHARS = 2000


@pytest.fixture
def loaded(monkeypatch, store_factory, make_profile):
    """The five native fixtures, a fresh sync stamp and a profile.

    `_open_store` is redirected at the FACTORY, not at a single Store: the
    tools run `with _open_store() as store` and Store.__exit__ closes the
    connection, so a second tool call in one test needs a fresh one. Without
    this redirect the tools read the operator's real 235-record index and the
    measurement below would not be reproducible.
    """
    import server

    monkeypatch.setattr(server, "_open_store", store_factory)
    store = store_factory()
    put_fixtures(store, NATIVE_IDS)
    store.set_meta("last_sync", ids.utcnow_iso())
    make_profile()
    return store


async def test_the_daily_brief_has_an_absolute_ceiling(loaded):
    import server

    result = await server.uplers_daily_brief(limit=3, since="2020-01-01", peek=True)

    assert isinstance(result, DailyBrief)
    payload = result.model_dump_json()
    # The window is wide open, so every fixture requisition is "new" - this is
    # the biggest this cohort's brief can get at limit=3.
    assert result.new_opportunities.count > 0, "an empty brief would pass vacuously"
    assert len(payload) < BRIEF_CEILING_CHARS, (
        "daily_brief grew to %d chars, ceiling is %d" % (len(payload), BRIEF_CEILING_CHARS)
    )


async def test_the_ceiling_is_not_vacuous(loaded):
    """The check must be capable of failing, so prove the margin is small.

    A ceiling with unlimited headroom certifies nothing. The real payload has
    to be within a factor of two of it, or this file is decoration.
    """
    import server

    result = await server.uplers_daily_brief(limit=3, since="2020-01-01", peek=True)
    actual = len(result.model_dump_json())

    assert actual > BRIEF_CEILING_CHARS / 2, (
        "the ceiling (%d) is more than twice the real size (%d) - it cannot fail"
        % (BRIEF_CEILING_CHARS, actual)
    )


async def test_a_wider_limit_costs_more_and_the_ceiling_tracks_the_limit(loaded):
    """The figure is per-`limit`; the ceiling above is only claimed for 3."""
    import server

    small = await server.uplers_daily_brief(limit=1, since="2020-01-01", peek=True)
    large = await server.uplers_daily_brief(limit=5, since="2020-01-01", peek=True)

    assert len(small.model_dump_json()) < len(large.model_dump_json())
