"""server.py - the MCP tool surface.

@mcp.tool() returns the plain function, so each tool is awaited directly.

Two guards apply to every test in this file:
  * _open_store is monkeypatched to a tmp_path-backed factory, so nothing can
    reach the real data/ directory;
  * server.UplersClient is replaced by a class that raises on construction, so
    any accidental network use fails the test instead of leaving the box. The
    two tests that legitimately fetch re-patch it with a MockTransport client.
"""

from __future__ import annotations

import httpx
import pytest

import server
from uplers_server import config
from uplers_server.client import UplersClient, UplersError
from uplers_server.models import (
    MarketStats,
    NewSinceResult,
    OpportunityDetail,
    SearchResult,
    SyncResult,
)

from conftest import (
    AGENTAI,
    AGGREGATED,
    ALL_IDS,
    ANOMALY,
    CONFIDO,
    GOFORMA,
    PRECISELY,
    load_fixture,
    make_transport,
    put_fixtures,
)

# The five read-only board tools this file was written for. The tier-2
# profile/tracking tools are exercised in test_tier2.py; both sets are counted
# together by the wiring test below.
BOARD_TOOL_NAMES = {
    "uplers_sync_index",
    "uplers_search_opportunities",
    "uplers_get_opportunity",
    "uplers_list_new_since",
    "uplers_get_market_stats",
}

TIER2_TOOL_NAMES = {
    "uplers_get_profile",
    "uplers_set_profile",
    "uplers_assess_fit",
    "uplers_rank_opportunities",
    "uplers_save_job",
    "uplers_list_saved",
    "uplers_unsave_job",
    "uplers_track",
    "uplers_update_status",
    "uplers_list_tracked",
    "uplers_set_alert",
    "uplers_list_alerts",
    "uplers_delete_alert",
    "uplers_daily_brief",
    "uplers_skill_gap",
    "uplers_company_intel",
    "uplers_scheduler_status",
}

#: The authenticated tier. Separated from the public tiers above because the
#: distinction is a safety property, not bookkeeping: every name in this set
#: needs a live session, and the last two are the only tools in the server that
#: can change anything on Uplers.
AUTH_TOOL_NAMES = {
    "uplers_login",
    "uplers_auth_status",
    # The session-lifecycle pair, added 2026-08-23 under the four-server auth
    # contract. `uplers_session_info` also answers with verify_live=False, at
    # which point it needs no session at all - it is filed here anyway,
    # because what it REPORTS ON is this tier and grouping it with the public
    # readers would hide that.
    "uplers_session_info",
    "uplers_logout",
    "uplers_my_feed",
    "uplers_my_pipeline",
    "uplers_get_opportunity_live",
    "uplers_tailored_jobs",
    "uplers_my_profile",
    "uplers_compare_profiles",
    "uplers_my_interviews",
    "uplers_my_assessments",
    "uplers_filter_options",
}

#: Added 2026-08-23. Their own set, not folded into AUTH_TOOL_NAMES, because
#: three of them read inside `talent/outreach/*` - the namespace of Uplers'
#: PAID outreach-agent product, which this server otherwise excludes.
#:
#: The exception is narrow and deliberate: he is paying for that agent and its
#: output was invisible here, so this server READS what an agent he already
#: owns has done. It does not run one, and it will not build one - a second
#: uncoordinated applier against a 250-requisition board where interest CANNOT
#: BE WITHDRAWN is the wrong answer. Keeping the set separate means a further
#: name appearing here is a decision somebody had to type, not a drift. Three
#: were typed for the agent-surface ring, whose routes were captured live on
#: 2026-08-23: the mailbox-scan consent read, the jobs that scan found, and the
#: agent's four settings surfaces. All three are GETs, and the intersection
#: assertion in the census below is what keeps that sentence true.
#:
#: The write half of that namespace stays unbuilt: `interview-feedback` and
#: `consent-email-job-scan`, the latter changing what Uplers reads out of his
#: mailbox. tests/test_agent_tools.py measures that no tool here reaches one.
AGENT_READ_TOOL_NAMES = {
    "uplers_agent_readthrough",
    "uplers_platform_saved_jobs",
    "uplers_my_preferences",
    "uplers_assessment_gates",
    "uplers_email_scan",
    "uplers_scanned_jobs",
    "uplers_agent_settings",
}

WRITE_TOOL_NAMES = {
    "uplers_apply",
    "uplers_dismiss",
}

#: Mutates LOCAL state only, and kept apart from WRITE_TOOL_NAMES on purpose.
#: That set means "can change something on Uplers", and the count assertion
#: below is the tripwire for a third such tool appearing. Filing a local-only
#: writer there would blunt the one invariant that matters.
#:
#: The sync tool is the direction of truth made executable: his Uplers profile
#: is authoritative, so it flows local <- Uplers and there is no counterpart
#: going the other way.
LOCAL_WRITE_TOOL_NAMES = {
    "uplers_sync_profile_from_uplers",
    "uplers_list_profile_snapshots",
    # A pure disk read, filed beside its exact sibling above rather than in a
    # set of its own: it lists resume restore points and cannot reach Uplers.
    "uplers_list_resume_snapshots",
}

#: The tools that can change HIM on Uplers, as opposed to acting on a
#: requisition. Separate from WRITE_TOOL_NAMES because they are a different
#: kind of act with a different worst case: `uplers_apply` sends an
#: application that cannot be withdrawn, which is irreversible but bounded -
#: one job. These replace a whole field on his profile, and the worst case is
#: losing data he typed in by hand. All four are confirm-gated and all four
#: snapshot before they send, because all four can destroy something.
#:
#: The resume pair is the newest and the sharpest. The profile pair overwrites
#: JSON this server also holds a copy of; the resume pair overwrites a FILE
#: that Uplers keeps no previous copy of - no history, no versions, no revert
#: route, and a download route that takes no "which resume" parameter. So for
#: those two the pre-flight snapshot is not a safety margin on top of a
#: recoverable act, it IS the only rollback in existence, which is why
#: `resume_write` refuses to send at all when the snapshot cannot be taken.
PROFILE_WRITE_TOOL_NAMES = {
    "uplers_update_profile",
    "uplers_restore_profile",
    "uplers_replace_resume",
    "uplers_restore_resume",
}

#: The shared-config surface, kept apart from every other set because its
#: blast radius is different in kind: this is the only tool in the server that
#: can write a file OTHER servers read. It writes the `candidate` section and
#: nothing else - never `scoring`, never a sibling server's block, never his
#: Uplers profile - and jobcore's apply_patch enforces that independently of
#: anything asserted here.
CONFIG_TOOL_NAMES = {
    "uplers_config",
}

#: Reads module constants and nothing else - no network, no database, no disk,
#: and no config write. Its own set because its blast radius is zero and it is
#: the one tool that must stay that way: it exists to be trusted when the
#: server's behaviour is already under suspicion.
INTROSPECTION_TOOL_NAMES = {
    "uplers_server_info",
}

TOOL_NAMES = (
    BOARD_TOOL_NAMES
    | TIER2_TOOL_NAMES
    | AUTH_TOOL_NAMES
    | AGENT_READ_TOOL_NAMES
    | WRITE_TOOL_NAMES
    | LOCAL_WRITE_TOOL_NAMES
    | PROFILE_WRITE_TOOL_NAMES
    | CONFIG_TOOL_NAMES
    | INTROSPECTION_TOOL_NAMES
)

S1 = "HR010126120000"   # 2026-01-01T12:00:00
S2 = "HR020126120000"   # 2026-01-02T12:00:00

LOC = "https://platform.uplers.com/talent/all-opportunities/%s"
SITEMAP = (
    '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
    "<url><loc>" + LOC % S1 + "</loc><lastmod>2026-01-01</lastmod></url>"
    "<url><loc>" + LOC % S2 + "</loc></url>"
    "</urlset>"
)


class NoNetwork:
    """Stand-in for UplersClient: constructing one is a test failure."""

    def __init__(self, *args, **kwargs):
        raise AssertionError("this tool must not construct an HTTP client")


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    monkeypatch.setattr(server, "UplersClient", NoNetwork)


@pytest.fixture
def tools(monkeypatch, store_factory):
    """Point the tools at a temp store; returns the factory for inspection."""
    monkeypatch.setattr(server, "_open_store", store_factory)
    return store_factory


def wire_client(monkeypatch, handler):
    """Let a tool build a real UplersClient, but over a MockTransport."""
    transport, calls = make_transport(handler)
    monkeypatch.setattr(
        server, "UplersClient", lambda *a, **k: UplersClient(transport=transport, delay=0)
    )
    return calls


# --- wiring (group H) -----------------------------------------------------


async def test_importing_server_registers_exactly_the_expected_tools():
    tools_listed = await server.mcp.list_tools()

    assert len(tools_listed) == 53
    assert {tool.name for tool in tools_listed} == TOOL_NAMES
    # The seven agent-read tools are READS. The counts below are what stops
    # that sentence from quietly becoming untrue: none of them may appear in
    # any write set, and no write set may grow to admit them.
    assert AGENT_READ_TOOL_NAMES & (
        WRITE_TOOL_NAMES | PROFILE_WRITE_TOOL_NAMES | CONFIG_TOOL_NAMES
    ) == set()
    assert len(AGENT_READ_TOOL_NAMES) == 7
    # The five original board tools must survive every later addition.
    assert BOARD_TOOL_NAMES <= {tool.name for tool in tools_listed}
    # The requisition-write surface stays exactly this size. A third tool that
    # can act on his account appearing without this line being edited is the
    # thing to catch.
    assert len(WRITE_TOOL_NAMES) == 2
    # And exactly one tool may write the SHARED config other servers read.
    assert len(CONFIG_TOOL_NAMES) == 1
    # And the surface that can change HIM stays exactly four: two writes and
    # the undo each one ships with. Nothing else may ever POST to his profile.
    # Moved 2 -> 4 on 2026-08-24 for the resume pair, as a typed decision -
    # which is the whole point of this line being here to be edited.
    assert len(PROFILE_WRITE_TOOL_NAMES) == 4
    # An "every write pairs with an undo" assertion was written here and then
    # DELETED, because planting a control proved it could not fail: the set is
    # already pinned exactly by the TOOL_NAMES equality above and by this len,
    # so every mutation that would have violated the pairing was caught two
    # lines earlier and the pairing line was never reached. A check that cannot
    # go red certifies nothing and reads as though it does. The pairing is
    # enforced where it can actually fail - tests/test_resume_write.py, where
    # removing the snapshot guard makes the write tests go red.
    # No `uplers_reauth`, and the absence is deliberate rather than pending.
    # Ruled 2026-08-23 with evidence: Uplers' durable layer is the token and
    # its SHORT layer is the browser profile - backwards from the siblings -
    # so there is nothing to renew from and a reauth here would be
    # `uplers_login` under another name. The reasoning ships to the operator
    # in uplers_session_info().renewal.why; this line is the tripwire.
    assert "uplers_reauth" not in {tool.name for tool in tools_listed}


async def test_every_tool_description_carries_its_docstring():
    for tool in await server.mcp.list_tools():
        function = getattr(server, tool.name)
        headline = (function.__doc__ or "").strip().splitlines()[0]

        assert len(headline) > 20
        assert tool.description is not None
        assert headline in tool.description


# --- the native / aggregated separation at tool level (group A) ----------


async def test_search_defaults_never_return_an_aggregated_row(tools):
    put_fixtures(tools(), ALL_IDS)

    result = await server.uplers_search_opportunities()

    assert isinstance(result, SearchResult)
    assert result.cohort == "native"
    assert result.searched == 5          # the aggregated record was not even scanned
    assert result.matched == 5
    assert AGGREGATED not in [row.hr_number for row in result.results]
    assert [row.is_native for row in result.results] == [True] * 5


async def test_include_aggregated_makes_the_scraped_cohort_reachable(tools):
    put_fixtures(tools(), ALL_IDS)

    result = await server.uplers_search_opportunities(
        include_aggregated=True, company="Databricks"
    )

    assert result.cohort == "native+aggregated"
    assert result.searched == 6
    assert result.matched == 1
    assert result.results[0].hr_number == AGGREGATED
    assert result.results[0].is_native is False
    assert any("Check `is_native` on each row." in note for note in result.notes)


# --- search behaviour -----------------------------------------------------


async def test_search_applies_filters_and_echoes_them_back(tools):
    put_fixtures(tools(), ALL_IDS)

    result = await server.uplers_search_opportunities(skill="python")

    assert result.matched == 1
    assert result.results[0].hr_number == AGENTAI
    assert result.filters_applied == {"skill": "python"}


async def test_search_limit_truncates_rows_but_not_the_match_count(tools):
    put_fixtures(tools(), ALL_IDS)

    result = await server.uplers_search_opportunities(limit=2)

    assert result.returned == 2
    assert len(result.results) == 2
    assert result.matched == 5
    assert any("Showing 2 of 5 matches" in note for note in result.notes)


async def test_search_reports_an_unknown_sort_instead_of_failing(tools):
    put_fixtures(tools(), ALL_IDS)

    result = await server.uplers_search_opportunities(sort="by_vibes")

    assert result.matched == 5
    assert any("Unknown sort 'by_vibes'" in note for note in result.notes)


async def test_search_reports_when_the_index_was_last_synced(tools):
    store = tools()
    put_fixtures(store, ALL_IDS)
    store.set_meta("last_sync", "2026-08-20T09:00:00")

    result = await server.uplers_search_opportunities()
    assert result.index_synced_at == "2026-08-20T09:00:00"


# --- loud failures at tool level (group F) -------------------------------


async def test_search_on_an_empty_index_raises_and_names_the_fix(tools):
    tools()  # create the (empty) database file

    with pytest.raises(UplersError) as excinfo:
        await server.uplers_search_opportunities(limit=5)

    message = str(excinfo.value)
    assert "uplers_sync_index()" in message
    assert "NOT 'no matching jobs'" in message


async def test_search_of_a_purely_aggregated_index_raises(tools):
    put_fixtures(tools(), [AGGREGATED])

    with pytest.raises(UplersError) as excinfo:
        await server.uplers_search_opportunities()

    assert "none are Uplers-native" in str(excinfo.value)


async def test_a_genuine_empty_result_says_so_instead_of_raising(tools):
    put_fixtures(tools(), ALL_IDS)

    result = await server.uplers_search_opportunities(skill="cobol")

    assert result.matched == 0
    assert result.results == []
    assert result.searched == 5
    assert result.notes != []
    assert any("genuine empty result" in note for note in result.notes)


async def test_get_opportunity_rejects_a_malformed_id_before_any_network(tools):
    tools()

    with pytest.raises(UplersError) as excinfo:
        await server.uplers_get_opportunity("not-an-id")

    assert "not a valid Uplers HR number" in str(excinfo.value)


async def test_list_new_since_raises_when_no_native_id_is_known(tools):
    tools()

    with pytest.raises(UplersError) as excinfo:
        await server.uplers_list_new_since("2026-01-01")

    assert "0 native requisitions" in str(excinfo.value)
    assert "uplers_sync_index()" in str(excinfo.value)


async def test_list_new_since_requires_a_date(tools):
    tools()

    with pytest.raises(UplersError) as excinfo:
        await server.uplers_list_new_since("   ")

    assert "iso_date is required" in str(excinfo.value)


async def test_market_stats_on_an_empty_index_raises(tools):
    tools()

    with pytest.raises(UplersError) as excinfo:
        await server.uplers_get_market_stats()

    assert "uplers_sync_index()" in str(excinfo.value)


# --- uplers_get_opportunity ----------------------------------------------


async def test_a_fresh_cached_record_is_served_without_building_a_client(tools):
    # The autouse `offline` fixture makes any client construction a failure.
    put_fixtures(tools(), [CONFIDO])

    detail = await server.uplers_get_opportunity(CONFIDO)

    assert isinstance(detail, OpportunityDetail)
    assert detail.hr_number == CONFIDO
    assert detail.company_info.name == "Confido Health"
    assert detail.pay.local_max == 3000000
    assert detail.is_native is True


async def test_full_description_flag_controls_truncation(tools):
    put_fixtures(tools(), [AGGREGATED])

    preview = await server.uplers_get_opportunity(AGGREGATED)
    whole = await server.uplers_get_opportunity(AGGREGATED, full_description=True)

    assert preview.description_truncated is True
    assert whole.description_truncated is False
    assert len(whole.description) > len(preview.description)


async def test_an_uncached_id_is_fetched_then_cached_and_indexed(tools, monkeypatch):
    store = tools()
    assert store.get_record(CONFIDO) is None

    calls = wire_client(
        monkeypatch, lambda request: httpx.Response(200, json=load_fixture(CONFIDO))
    )

    detail = await server.uplers_get_opportunity(CONFIDO)

    assert detail.hr_number == CONFIDO
    assert [c.url.params["hr_number"] for c in calls] == [CONFIDO]

    after = tools()
    assert after.get_record(CONFIDO)[0]["HR_Number"] == CONFIDO
    assert CONFIDO in after.known_ids()   # the id is unioned in, not just cached


# --- uplers_list_new_since ------------------------------------------------


async def test_list_new_since_returns_hydrated_rows_newest_first(tools):
    store = tools()
    store.union_ids({hr: None for hr in ALL_IDS})
    put_fixtures(store, ALL_IDS)

    result = await server.uplers_list_new_since("2026-01-01")

    assert isinstance(result, NewSinceResult)
    assert result.since == "2026-01-01T00:00:00"        # bare dates are widened
    assert [row.hr_number for row in result.results] == [AGENTAI, PRECISELY]
    assert result.matched == 2
    assert result.returned == 2
    assert result.unhydrated == []
    assert result.known_native_ids == 4                 # the 13-digit id is not native
    assert ANOMALY not in [row.hr_number for row in result.results]


async def test_known_but_unfetched_ids_are_reported_not_dropped(tools):
    store = tools()
    store.union_ids({S1: None, S2: None})   # ids indexed, records never fetched

    result = await server.uplers_list_new_since("2026-01-01")

    assert result.results == []
    assert result.matched == 0
    assert result.unhydrated == [S2, S1]
    assert result.known_native_ids == 2
    assert any("known but not yet fetched" in note for note in result.notes)


async def test_unhydrated_ids_can_be_suppressed(tools):
    store = tools()
    store.union_ids({S1: None, S2: None})

    result = await server.uplers_list_new_since("2026-01-01", include_unhydrated=False)
    assert result.unhydrated == []


async def test_list_new_since_with_no_hits_is_a_genuine_zero(tools):
    store = tools()
    store.union_ids({hr: None for hr in ALL_IDS})
    put_fixtures(store, ALL_IDS)

    result = await server.uplers_list_new_since("2027-01-01")

    assert result.matched == 0
    assert result.known_native_ids == 4
    assert any("genuine zero" in note for note in result.notes)


# --- uplers_get_market_stats ---------------------------------------------


async def test_market_stats_groups_the_native_cohort(tools):
    put_fixtures(tools(), ALL_IDS)

    stats = await server.uplers_get_market_stats(group_by="currency", min_group_size=1)

    assert isinstance(stats, MarketStats)
    assert stats.cohort == "native"
    assert stats.population == 5
    assert [(g.key, g.count) for g in stats.groups] == [("INR", 3), ("GBP", 1), ("USD", 1)]
    assert any("n_with_pay" in note for note in stats.notes)


async def test_market_stats_can_fold_in_the_aggregated_cohort(tools):
    put_fixtures(tools(), ALL_IDS)

    stats = await server.uplers_get_market_stats(
        group_by="currency", min_group_size=1, include_aggregated=True
    )

    assert stats.cohort == "native+aggregated"
    assert stats.population == 6
    assert [(g.key, g.count) for g in stats.groups] == [("INR", 4), ("GBP", 1), ("USD", 1)]


async def test_market_stats_flags_an_unknown_group_by(tools):
    put_fixtures(tools(), ALL_IDS)

    stats = await server.uplers_get_market_stats(group_by="constellation")

    assert stats.group_by == "role"
    assert stats.notes[0] == "Unknown group_by 'constellation'; grouped by 'role' instead."


# --- uplers_sync_index ----------------------------------------------------


async def test_sync_index_tool_builds_the_index_through_its_client(tools, monkeypatch):
    def handler(request):
        if request.url.path == config.SITEMAP_PATH:
            return httpx.Response(200, text=SITEMAP)
        raw = dict(load_fixture(AGENTAI))
        raw["HR_Number"] = request.url.params["hr_number"]
        return httpx.Response(200, json=raw)

    calls = wire_client(monkeypatch, handler)

    result = await server.uplers_sync_index()

    assert isinstance(result, SyncResult)
    assert result.sitemap_entries == 2
    assert result.new_ids == 2
    assert result.new_native_ids == 2
    assert result.total_known_native == 2
    assert result.records_fetched == 2
    assert result.newest_native == [S2, S1]
    assert len(calls) == 3   # 1 sitemap + 2 records

    store = tools()
    assert store.cached_ids() == {S1, S2}
    assert store.last_sync is not None


async def test_sync_index_tool_respects_hydrate_false(tools, monkeypatch):
    calls = wire_client(monkeypatch, lambda request: httpx.Response(200, text=SITEMAP))

    result = await server.uplers_sync_index(hydrate=False)

    assert result.new_ids == 2
    assert result.records_fetched == 0
    assert len(calls) == 1
    assert tools().cached_ids() == set()
