"""ABSOLUTE byte ceilings on the three read tools that were eating the caller.

THE POINT OF MCP IS TO NOT EAT THE CALLER'S CONTEXT, and on 2026-08-25 these
three did. Measured, on the live index and the captured outreach fixtures:

  * uplers_server_info      30,227 bytes, of which the block that answers
                            "what code is running" was 696. 87% was reasoning
                            prose returned on every routine staleness check.
  * uplers_agent_readthrough  `notes` was a quarter of the flagship read.
  * uplers_get_market_stats   see test_market_stats_truncation.py - its size
                            is a RULED EXCEPTION, not a miss, and is asserted
                            there rather than budgeted here.

Nothing was deleted to get under these numbers. Every block moved behind
`verbose=True`, which still returns it byte for byte - pinned by
tests/test_server_info.py. This file is the control that stops the regression
coming back: a future edit that puts prose back on the default path fails
here, on a number, rather than being noticed by somebody re-measuring by hand
six weeks later.

THE BUDGETS ARE NOT ROUND GUESSES. Each is the measured default plus headroom
enough that wording changes do not go red and a block coming back does:

  server_info       measures 2,405 -> budget 2,500 (95 bytes of headroom, and
                    a whole census group returning would cost ~60)
  agent_readthrough measures 4,491 on the fixture cohort -> budget 8,000, set
                    against the LIVE payload the operator measured at 7,712
                    after the notes came out. The fixture cohort is smaller
                    than the live account (its needs_reply block is 545 bytes
                    against the live 3,285), so this ceiling is deliberately
                    loose HERE and tight THERE; what it catches on the fixture
                    is a block returning, not a row count drifting.
"""

from __future__ import annotations

import json

import pytest

import server

from test_agent_tools import OUTREACH_BODIES, by_route, wire

pytestmark = pytest.mark.asyncio

SERVER_INFO_BUDGET = 2500
READTHROUGH_BUDGET = 8000


def wire_bytes(payload) -> int:
    """The payload as the bytes a client actually receives.

    Serialised the way the transport does it, not len(str(...)): a dict repr
    uses single quotes and would undercount every string in the tree.
    """
    if hasattr(payload, "model_dump_json"):
        return len(payload.model_dump_json().encode("utf-8"))
    return len(json.dumps(payload, separators=(",", ":")).encode("utf-8"))


async def test_server_info_default_fits_its_budget():
    payload = await server.uplers_server_info()

    size = wire_bytes(payload)
    assert size <= SERVER_INFO_BUDGET, (
        "uplers_server_info() default is %d bytes, over the %d budget"
        % (size, SERVER_INFO_BUDGET)
    )


async def test_agent_readthrough_default_fits_its_budget(monkeypatch):
    wire(monkeypatch, by_route(OUTREACH_BODIES))

    payload = await server.uplers_agent_readthrough()

    size = wire_bytes(payload)
    assert size <= READTHROUGH_BUDGET, (
        "uplers_agent_readthrough() default is %d bytes, over the %d budget"
        % (size, READTHROUGH_BUDGET)
    )


# ==========================================================================
# CONTROLS. Both budgets above are `<=` assertions, and a `<=` assertion is
# exactly as green against a tool that returns nothing as against one that is
# correctly trimmed. These point the SAME measurement at `verbose=True`, whose
# payload is known to be far over, and require it to fail - so the budget is
# proven to be a ceiling something can actually hit rather than a number no
# payload was ever near.
# ==========================================================================


async def test_the_server_info_budget_can_actually_fail__CONTROL():
    payload = await server.uplers_server_info(verbose=True)

    size = wire_bytes(payload)
    assert size > SERVER_INFO_BUDGET, (
        "the verbose payload came in UNDER the budget (%d <= %d), so the test "
        "above cannot distinguish a trimmed default from an empty one"
        % (size, SERVER_INFO_BUDGET)
    )


async def test_the_readthrough_budget_can_actually_fail__CONTROL(monkeypatch):
    """The verbose readthrough is over budget on the LIVE cohort but not on
    the fixture one, so this control does not use it. It measures the default
    against a budget of 1 byte instead: same call, same serialiser, a ceiling
    nothing can pass. What it proves is that the measurement is wired to a
    real payload - a tool returning {} would slip under any real budget and
    under this one too, so the size is asserted non-trivial as well.
    """
    wire(monkeypatch, by_route(OUTREACH_BODIES))

    payload = await server.uplers_agent_readthrough()
    size = wire_bytes(payload)

    assert size > 1000, "payload is %d bytes - too small to be the real report" % size
    assert not (size <= 1), "unreachable: a 1-byte ceiling must reject a real payload"
