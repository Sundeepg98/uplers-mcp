"""`explain=True` on the nine scoring tools, and the two hashes it carries.

jobcore has been able to hand back the arithmetic behind a fit score since it
gained ``FitScore.explain()``; until now nothing in this server could ask for
it, so every score arrived as a bare number with no account of itself. These
tests pin the switch that fixes that, and they are written around the two ways
such a switch goes wrong.

**It leaks when nobody asked.** Token cost is this server's governing
constraint - `RankedRow` drops URLs and trims timestamps over single-digit
character counts - and an explain block is roughly the size of the row it
describes. So the default is not merely "empty": the key must be ABSENT from
the serialised response. `Compact` prunes None, which is what makes that
achievable; every test below asserts on the JSON text rather than on the
attribute, because `row.explain is None` would pass even if the wire carried
``"explain": null`` on every row of every ranking.

**It echoes constants and proves nothing.** A block that reports the weights
and the bonus table without those numbers actually adding up to the score is
decoration. `test_the_block_reproduces_the_score` recomputes the score from
the block's own fields and would fail if the two ever drifted apart.

The third thing here is the hash rename that rode in with it. Two different
fingerprints were both called ``policy_hash``: one over ``{scoring,
candidate}``, one over ``{scoring}`` alone. Comparing a stored score's stamp
against a config readout therefore reported a difference that did not exist,
on the single field whose whole job is to say whether two scores are
comparable. A scored result now carries ``scoring_hash``; a config readout
carries both, and says which answers which question.
"""

from __future__ import annotations

import json

import pytest

import server
from test_talent_tools import auth_record, feed_handler, serve, wire_talent
from uplers_server import fit
from uplers_server import policy as policy_mod
from uplers_server.models import Opportunity, SkillSet
from uplers_server.shaping import to_opportunity

from conftest import AGENTAI, NATIVE_IDS, load_fixture, put_fixtures
from uplers_server import ids


# --- harness --------------------------------------------------------------


class NoNetwork:
    def __init__(self, *args, **kwargs):
        raise AssertionError("this tool must not construct a public HTTP client")


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    monkeypatch.setattr(server, "UplersClient", NoNetwork)


@pytest.fixture(autouse=True)
def tools(monkeypatch, store_factory):
    monkeypatch.setattr(server, "_open_store", store_factory)
    return store_factory


@pytest.fixture
async def ready(tools, make_profile):
    """One store that satisfies all six local tools at once.

    The five native fixtures cached, a profile, one saved role and one
    score-gated alert - the last because `uplers_list_alerts` only scores when
    a criterion needs a score, so an ungated alert would evaluate without ever
    reaching `fit.assess` and the explain assertion would pass vacuously.
    """
    store = tools()
    put_fixtures(store, NATIVE_IDS)
    store.set_meta("last_sync", ids.utcnow_iso())
    make_profile()
    await server.uplers_save_job(AGENTAI)
    await server.uplers_set_alert("remote", remote_only=True, min_score=1)
    return store


def serialised(result) -> str:
    return result.model_dump_json()


def carries_explain(result) -> bool:
    """Is there an `explain` key ANYWHERE in the serialised response?

    Deliberately a text search over the whole payload rather than an attribute
    check on one row: these tools nest scored rows several levels down (a
    brief carries alert hits which carry rows), and the question is what
    crosses the wire, not what one object happens to hold.
    """
    return '"explain":' in serialised(result)


#: The six tools that score locally, with the smallest call that reaches a
#: score. `uplers_list_alerts` needs evaluate=True or it scores nothing, and
#: `uplers_daily_brief` is called with peek=True because it is designed to
#: consume its own news - a second call without peek reports an empty alert
#: section by design, which would make the byte-identity comparison below
#: measure that instead of the switch. peek changes only what is WRITTEN; the
#: ranking and the alert evaluation both still score.
LOCAL_TOOLS = [
    ("uplers_assess_fit", {"hr_number": AGENTAI}),
    ("uplers_rank_opportunities", {"limit": 3}),
    ("uplers_list_saved", {}),
    ("uplers_list_alerts", {"evaluate": True}),
    ("uplers_daily_brief", {"since": "2020-01-01", "peek": True}),
    ("uplers_company_intel", {"name": "AgentAI"}),
]

LOCAL_IDS = [name for name, _ in LOCAL_TOOLS]


# ==========================================================================
# GROUP 1 - the six local tools.
# ==========================================================================


@pytest.mark.parametrize("tool_name,kwargs", LOCAL_TOOLS, ids=LOCAL_IDS)
async def test_the_default_response_has_no_explain_key_at_all(
    ready, tool_name, kwargs
):
    """Not null, not empty - absent. See the module docstring."""
    result = await getattr(server, tool_name)(**kwargs)

    assert carries_explain(result) is False
    assert "explain" not in serialised(result)


@pytest.mark.parametrize("tool_name,kwargs", LOCAL_TOOLS, ids=LOCAL_IDS)
async def test_asking_for_it_produces_a_block(ready, tool_name, kwargs):
    result = await getattr(server, tool_name)(explain=True, **kwargs)

    assert carries_explain(result) is True


@pytest.mark.parametrize("tool_name,kwargs", LOCAL_TOOLS, ids=LOCAL_IDS)
async def test_explain_false_is_byte_identical_to_not_passing_it(
    ready, tool_name, kwargs
):
    """The switch must not perturb the default response by existing.

    `uplers_list_alerts(evaluate=True)` records its hits, so the second call
    honestly reports zero NEW matches; that field and the timestamp beside it
    are dropped before comparing, and everything else must match exactly.
    """
    tool = getattr(server, tool_name)
    first = json.loads(serialised(await tool(**kwargs)))
    second = json.loads(serialised(await tool(explain=False, **kwargs)))

    for payload in (first, second):
        payload.pop("generated_at", None)
        for alert in payload.get("alerts", []) + payload.get("alert_hits", []):
            alert.pop("new_matches", None)
            alert.pop("last_evaluated_at", None)

    assert second == first


async def test_the_block_lands_on_the_row_it_describes(ready):
    """Per-row, not once per response. A ranking scores each row separately."""
    result = await server.uplers_rank_opportunities(limit=3, explain=True)

    assert len(result.rows) > 1
    for row in result.rows:
        assert row.explain is not None
        assert row.explain["overall_score"] == row.score


async def test_a_ranking_row_grows_only_when_asked(ready):
    """The reason it is off by default, as a measurement rather than a claim."""
    plain = await server.uplers_rank_opportunities(limit=1)
    loud = await server.uplers_rank_opportunities(limit=1, explain=True)

    assert len(loud.rows[0].model_dump_json()) > len(plain.rows[0].model_dump_json())
    assert plain.rows[0].score == loud.rows[0].score


# ==========================================================================
# GROUP 2 - the three authenticated tools.
#
# Wired exactly as test_talent_tools.py wires them: a real TalentClient over a
# MockTransport, with the token supplied directly, so nothing reads the
# operator's session file and nothing leaves the box.
# ==========================================================================


AUTH_TOOLS = [
    ("uplers_my_feed", {}),
    ("uplers_my_pipeline", {"score": True}),
    ("uplers_tailored_jobs", {}),
]

AUTH_IDS = [name for name, _ in AUTH_TOOLS]


def wire_for(monkeypatch, tool_name):
    """The handler each authenticated read expects to be answered with."""
    if tool_name == "uplers_tailored_jobs":
        return wire_talent(monkeypatch, serve({"data": [auth_record()]}))
    return wire_talent(monkeypatch, feed_handler(total=1))


@pytest.mark.parametrize("tool_name,kwargs", AUTH_TOOLS, ids=AUTH_IDS)
async def test_an_authenticated_row_has_no_explain_key_by_default(
    monkeypatch, make_profile, tool_name, kwargs
):
    make_profile()
    wire_for(monkeypatch, tool_name)

    result = await getattr(server, tool_name)(**kwargs)

    assert result.rows[0].score is not None      # it really did score
    assert carries_explain(result) is False


@pytest.mark.parametrize("tool_name,kwargs", AUTH_TOOLS, ids=AUTH_IDS)
async def test_an_authenticated_row_explains_when_asked(
    monkeypatch, make_profile, tool_name, kwargs
):
    make_profile()
    wire_for(monkeypatch, tool_name)

    result = await getattr(server, tool_name)(explain=True, **kwargs)

    assert result.rows[0].explain is not None
    assert result.rows[0].explain["overall_score"] == result.rows[0].score


@pytest.mark.parametrize("tool_name", ["uplers_my_feed", "uplers_tailored_jobs"])
async def test_score_false_with_explain_true_is_a_no_op_not_an_error(
    monkeypatch, make_profile, tool_name
):
    """The combination a caller will try first, and it must not raise.

    There is no score without a profile to score against, so there is nothing
    to explain either. The honest answer is an unscored row, not an exception
    and not a block full of nulls.
    """
    make_profile()
    wire_for(monkeypatch, tool_name)

    result = await getattr(server, tool_name)(score=False, explain=True)

    assert result.rows[0].score is None
    assert carries_explain(result) is False


async def test_list_saved_explains_nothing_when_it_scores_nothing(ready):
    """Same rule on the local side, where `score` and `explain` also meet."""
    result = await server.uplers_list_saved(score=False, explain=True)

    assert result.saved[0].score is None
    assert carries_explain(result) is False


# ==========================================================================
# GROUP 3 - the block is arithmetic, not decoration.
# ==========================================================================


@pytest.fixture
def scored(make_profile):
    """One real requisition scored with the working shown."""
    profile = make_profile()
    opp = to_opportunity(load_fixture(AGENTAI))
    return fit.assess(opp, profile, explain=True)


def test_the_block_reproduces_the_score(scored):
    """THE test in this file.

    A block that only echoed the policy would satisfy every other assertion
    here. This one recomputes the score from the block's own numbers - the
    weighted combination of the two base components, plus the capped bonus
    total, rounded, ceilinged at 100 - and compares it with the score that was
    actually returned. If jobcore's arithmetic and its account of that
    arithmetic ever part company, this fails and nothing else does.
    """
    block = scored["explain"]
    base = block["base"]
    bonuses = block["bonuses"]

    recomputed = min(100, round(base["combined"] + bonuses["total"]))

    assert recomputed == block["overall_score"] == scored["overall_score"]


def test_the_combination_is_the_two_components_under_the_declared_weights(scored):
    block = scored["explain"]
    weights = block["weights"]
    base = block["base"]

    combined = base["skills"] * weights["skills"] + base["experience"] * weights["experience"]

    assert round(combined, 1) == pytest.approx(base["combined"], abs=0.1)
    assert weights["skills"] + weights["experience"] == pytest.approx(1.0)


def test_the_bonus_total_is_the_raw_total_under_the_cap(scored):
    bonuses = scored["explain"]["bonuses"]
    parts = ["location", "work_mode", "salary", "agent_eligible"]

    assert sum(bonuses[part] for part in parts) == bonuses["raw_total"]
    assert bonuses["total"] == min(bonuses["raw_total"], bonuses["cap"])
    assert scored["explain"]["bonus_cap_applied"] is (bonuses["raw_total"] > bonuses["cap"])


def test_the_block_carries_scoring_hash_and_not_policy_hash(scored):
    """The rename, at the one place it decides anything.

    A result can only vouch for the ARITHMETIC. The candidate half of the
    policy is a call argument here, so stamping a hash that covered it would
    make two perfectly comparable scores look incomparable.
    """
    block = scored["explain"]

    assert "scoring_hash" in block
    assert "policy_hash" not in block
    assert block["scoring_hash"] == policy_mod.DEFAULTS.scoring_hash
    assert block["scoring_hash"] != policy_mod.DEFAULTS.policy_hash


# ==========================================================================
# GROUP 4 - _profile_summary now carries both hashes, and they are different.
# ==========================================================================


def a_role() -> Opportunity:
    return Opportunity(
        hr_number="HR010126120010",
        title="Backend Engineer",
        company="Acme",
        min_years_experience=3.0,
        max_years_experience=8.0,
        city="Bangalore",
        mode_of_work="Remote",
        joining_period="30 Days",
        skills=SkillSet(must_have=["Node.js", "PostgreSQL", "AWS"]),
    )


@pytest.fixture
def both_halves_configured(tmp_path, monkeypatch):
    """A policy whose CANDIDATE and SCORING are both off the defaults.

    Both halves, on purpose: with only `scoring` edited the two fingerprints
    would still differ, but the test would not show WHY - it is the candidate
    half being inside one hash and outside the other that the rename is about.
    """
    path = tmp_path / "jobhunt.json"
    path.write_text(
        json.dumps(
            {
                "candidate": {"skills": ["rust", "go"], "notice_period_days": 45},
                "scoring": {"weights": {"skills": 0.7, "experience": 0.3}},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("JOBHUNT_CONFIG", str(path))
    policy_mod.invalidate()
    yield policy_mod.bind()
    policy_mod.invalidate()


def test_the_summary_carries_both_hashes_and_they_differ(
    both_halves_configured, make_profile
):
    bound = both_halves_configured
    summary = server._profile_summary(make_profile(), bound)

    assert summary.policy_hash == bound.policy_hash
    assert summary.scoring_hash == bound.scoring_hash
    assert summary.policy_hash != summary.scoring_hash


def test_neither_hash_is_truncated(both_halves_configured, make_profile):
    """The old code sliced `[:12]` off a value that was already 12 characters.

    Harmless, and a lie about the shape of the field: a reader who saw a slice
    would reasonably assume the full value was longer and comparable to
    something else.
    """
    summary = server._profile_summary(make_profile(), both_halves_configured)

    assert len(summary.policy_hash) == 12
    assert len(summary.scoring_hash) == 12
    assert summary.policy_hash == both_halves_configured.loaded.policy_hash


def test_the_summarys_scoring_hash_is_the_one_stamped_on_a_result(
    both_halves_configured, make_profile
):
    """The bridge the rename exists to build, asserted end to end.

    Under a non-default policy jobcore stamps the result automatically. That
    stamp, the block's hash and the summary's `scoring_hash` must be one
    value - otherwise "is this stored score current?" stays unanswerable,
    which is the failure the whole rename was for.
    """
    bound = both_halves_configured
    profile = make_profile()
    summary = server._profile_summary(profile, bound)

    result = fit.assess(a_role(), profile, bound, explain=True)

    assert result["scoring_hash"] == summary.scoring_hash
    assert result["explain"]["scoring_hash"] == summary.scoring_hash
    assert result["scoring_hash"] != summary.policy_hash


async def test_the_config_readout_reports_both_and_says_which_is_which(
    both_halves_configured, make_profile
):
    """uplers_config() is where a human resolves a comparability question."""
    make_profile()

    report = await server.uplers_config()

    assert report.policy_hash == both_halves_configured.policy_hash
    assert report.scoring_hash == both_halves_configured.scoring_hash
    assert report.policy_hash != report.scoring_hash


async def test_a_scored_response_carries_both_hashes_beside_the_score(ready):
    """Every scored result already attaches `scored_against`; it now says both."""
    result = await server.uplers_assess_fit(AGENTAI)

    assert result.scored_against.policy_hash == policy_mod.DEFAULTS.policy_hash
    assert result.scored_against.scoring_hash == policy_mod.DEFAULTS.scoring_hash
    assert result.scored_against.policy_hash != result.scored_against.scoring_hash
