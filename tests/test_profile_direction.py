"""Which profile is the source of truth, and which way a fix flows.

The operator's instruction, verbatim: *"i have already updated my uplers
profile on my auth version. pls follow it dont overwrite."*

That settles a question this server had answered backwards. There are two
profiles. His UPLERS profile is the one he maintains, the one recruiters see,
and the one Uplers' own matching runs against - it is AUTHORITATIVE. The local
`data/profile.json` exists for exactly one reason: fit scores need a candidate
to score against. It is a cache of him, not a record of him.

Two consequences, both tested here:

  * `uplers_compare_profiles` must recommend fixing the LOCAL side. It used to
    tell him to go and add skills on platform.uplers.com, which is instructing
    him to edit the authoritative record to match its own cache.
  * The two profile ROUTES are never confused. This server can write to his
    Uplers profile - `uplers_update_profile` - but that write goes to
    `talent/profile-upsert`, which REPLACES a whole field. The plain
    `talent/profile` route stays read-only here. The guarantees about how the
    write may be INVOKED live in `test_profile_write.py`; what this file pins
    is that the read route never becomes a write one.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from test_talent_tools import serve, wire_talent, writes  # noqa: F401
from uplers_server import endpoints, profile as profile_mod, talent_shape
from uplers_server.talent_models import ProfileComparison

import server

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "talent_profile.json"


@pytest.fixture
def real_payload() -> dict:
    with FIXTURE.open(encoding="utf-8") as handle:
        return json.load(handle)


# --- direction of truth ----------------------------------------------------


async def test_the_recommendation_points_at_the_local_profile_not_uplers(
    monkeypatch, make_profile, real_payload
):
    """THE regression. It told him to edit the authoritative record.

    Against his real captured profile the old wording produced "Your Uplers
    profile is thinner than your local one (0 skills there vs 32 here)" - a
    sentence that was wrong twice over: the direction was backwards AND the
    zero was a extraction bug.
    """
    make_profile(skills=["Node.js", "TypeScript", "AWS"])
    wire_talent(monkeypatch, serve(real_payload))

    result = await server.uplers_compare_profiles()

    assert isinstance(result, ProfileComparison)
    assert result.source_of_truth == "uplers"

    text = " ".join([result.recommendation or ""] + result.notes)
    assert "platform.uplers.com" not in text
    assert "thinner" not in text
    assert "uplers_sync_profile_from_uplers" in text


async def test_skills_only_on_uplers_are_reported_as_a_LOCAL_gap(
    monkeypatch, make_profile, real_payload
):
    """They are not missing from Uplers. They are missing from the scorer."""
    make_profile(skills=["Node.js", "TypeScript"])
    wire_talent(monkeypatch, serve(real_payload))

    result = await server.uplers_compare_profiles()

    assert len(result.only_uplers) > 20
    note = " ".join(result.notes)
    assert "fit score" in note.lower()


async def test_a_genuine_disagreement_is_surfaced_and_never_auto_resolved(
    monkeypatch, make_profile, real_payload
):
    """His headline and his years differ between the two records.

    Uplers says "Software Engineer" and 5.2; the local file says "Backend
    Software Engineer" and 5.0. Neither is obviously right - a headline is a
    positioning choice and 0.2 years is a rounding convention - so this server
    reports the pair and stops. Picking one would be the server overruling him
    on a judgement it has no basis for.
    """
    make_profile(headline="Backend Software Engineer", years_experience=5.0)
    wire_talent(monkeypatch, serve(real_payload))

    result = await server.uplers_compare_profiles()

    contested = {entry.field for entry in result.needs_your_decision}
    assert "headline" in contested
    assert "years_experience" in contested

    for entry in result.needs_your_decision:
        assert entry.local and entry.uplers


async def test_a_field_the_two_agree_on_is_not_dressed_up_as_a_conflict(
    monkeypatch, make_profile, real_payload
):
    """Notice period already agrees - Immediately on Uplers, 0 days locally."""
    make_profile(notice_period_days=0)
    wire_talent(monkeypatch, serve(real_payload))

    result = await server.uplers_compare_profiles()

    assert "notice_period" in result.agree
    assert "notice_period" not in {entry.field for entry in result.needs_your_decision}


# --- the sync tool ---------------------------------------------------------


async def test_sync_without_confirm_previews_and_writes_nothing(
    monkeypatch, make_profile, real_payload, isolated_profile
):
    make_profile(skills=["Node.js"])
    before = isolated_profile.read_bytes()
    wire_talent(monkeypatch, serve(real_payload))

    result = await server.uplers_sync_profile_from_uplers()

    assert result.applied is False
    assert result.skills_added
    assert isolated_profile.read_bytes() == before


async def test_sync_with_confirm_updates_local_and_says_exactly_what_changed(
    monkeypatch, make_profile, real_payload, isolated_profile
):
    make_profile(skills=["Node.js", "TypeScript"])
    wire_talent(monkeypatch, serve(real_payload))

    result = await server.uplers_sync_profile_from_uplers(confirm=True)

    assert result.applied is True
    assert "Kubernetes" in result.skills_added
    assert result.skills_before == 2
    assert result.skills_after > 50

    saved = profile_mod.load(path=isolated_profile)
    assert "Kubernetes" in saved.skills
    assert "Node.js" in saved.skills


async def test_sync_snapshots_the_local_profile_so_it_is_restorable(
    monkeypatch, make_profile, real_payload, isolated_profile
):
    """A destructive-feeling operation the operator cannot undo is a trap.

    He gets the backup path back in the result, and it holds the profile as it
    was BEFORE the sync - which is the only thing that makes the sync safe to
    try.
    """
    original = make_profile(skills=["Node.js", "TypeScript"])
    wire_talent(monkeypatch, serve(real_payload))

    result = await server.uplers_sync_profile_from_uplers(confirm=True)

    assert result.backup_path
    backup = Path(result.backup_path)
    assert backup.is_file()
    assert json.loads(backup.read_text(encoding="utf-8"))["skills"] == original.skills


async def test_sync_keeps_local_only_skills_rather_than_deleting_them(
    monkeypatch, make_profile, real_payload, isolated_profile
):
    """MEASURED, and the reason this defaults to a union rather than a replace.

    Scoring the 243 cached requisitions against his real Uplers skill set
    moved 73 of them, 71 upward - but two Atmail roles went DOWN, because the
    local profile carries seven email-infrastructure skills (SMTP, email
    deliverability, bulk email systems, RabbitMQ...) that his Uplers profile
    does not list. A replace would delete real capability and quietly demote
    every email role. A union takes everything Uplers knows without discarding
    what it has not been told.
    """
    make_profile(skills=["SMTP", "Email Deliverability", "Node.js"])
    wire_talent(monkeypatch, serve(real_payload))

    result = await server.uplers_sync_profile_from_uplers(confirm=True)

    saved = profile_mod.load(path=isolated_profile)
    assert "SMTP" in saved.skills
    assert "Email Deliverability" in saved.skills
    assert result.skills_removed == []
    assert result.local_only_kept


async def test_sync_leaves_the_contested_fields_alone_unless_asked(
    monkeypatch, make_profile, real_payload, isolated_profile
):
    """Headline and years are his call, so a default sync does not touch them."""
    make_profile(headline="Backend Software Engineer", years_experience=5.0)
    wire_talent(monkeypatch, serve(real_payload))

    await server.uplers_sync_profile_from_uplers(confirm=True)

    saved = profile_mod.load(path=isolated_profile)
    assert saved.headline == "Backend Software Engineer"
    assert saved.years_experience == 5.0


async def test_a_contested_headline_cannot_reach_titles_through_a_side_door(
    monkeypatch, make_profile, real_payload, isolated_profile
):
    """Caught in review of the first cut of this tool, which did exactly this.

    `titles` was synced as `remote.titles or [remote.headline]`. Uplers reports
    no roles list, so the fallback fired and every default sync quietly wrote
    the contested headline into `titles` - a field that biases ranking. "Your
    headline is your call" would have been true of one field and false in
    effect.
    """
    make_profile(headline="Backend Software Engineer", titles=["Backend Software Engineer"])
    wire_talent(monkeypatch, serve(real_payload))

    result = await server.uplers_sync_profile_from_uplers(confirm=True)

    saved = profile_mod.load(path=isolated_profile)
    assert saved.titles == ["Backend Software Engineer"]
    assert "titles" not in {change.field for change in result.fields_changed}


async def test_sync_can_take_a_contested_field_when_he_names_it(
    monkeypatch, make_profile, real_payload, isolated_profile
):
    make_profile(headline="Backend Software Engineer", years_experience=5.0)
    wire_talent(monkeypatch, serve(real_payload))

    result = await server.uplers_sync_profile_from_uplers(
        confirm=True, also=["headline", "years_experience"]
    )

    saved = profile_mod.load(path=isolated_profile)
    assert saved.headline == "Software Engineer"
    assert saved.years_experience == 5.2
    assert {change.field for change in result.fields_changed} >= {
        "headline",
        "years_experience",
    }


async def test_a_misspelled_contested_field_is_refused_rather_than_ignored(
    monkeypatch, make_profile, real_payload
):
    """Silently dropping `also=["headlin"]` leaves him believing he synced it.

    The whole point of `also` is that he made a decision about a contested
    field. Swallowing the typo discards the decision and reports success.
    """
    make_profile()
    wire_talent(monkeypatch, serve(real_payload))

    with pytest.raises(Exception) as excinfo:
        await server.uplers_sync_profile_from_uplers(confirm=True, also=["headlin"])

    assert "headlin" in str(excinfo.value)
    assert "headline" in str(excinfo.value)


async def test_a_zero_skill_read_is_refused_rather_than_synced(
    monkeypatch, make_profile, isolated_profile
):
    """The original bug, turned into a guard on the tool it would damage most.

    A profile that resolves to zero skills is far more likely to be a broken
    read than an empty account - that is precisely what happened here. Syncing
    it would propagate the breakage into the local file and wipe his real
    skills on a `replace_skills` run.
    """
    make_profile(skills=["Node.js", "TypeScript"])
    before = isolated_profile.read_bytes()
    wire_talent(monkeypatch, serve({"talent_details": {"full_name": "Sundeep G"}}))

    with pytest.raises(Exception) as excinfo:
        await server.uplers_sync_profile_from_uplers(confirm=True)

    assert "zero skills" in str(excinfo.value)
    assert isolated_profile.read_bytes() == before


async def test_sync_makes_no_request_other_than_reading_the_profile(
    monkeypatch, make_profile, real_payload
):
    make_profile()
    calls = wire_talent(monkeypatch, serve(real_payload))

    await server.uplers_sync_profile_from_uplers(confirm=True)

    assert writes(calls) == []
    assert [call.url.path for call in calls] == ["/api/" + endpoints.EP_PROFILE]


# --- the route separation --------------------------------------------------
#
# This server CAN write to his Uplers profile - `uplers_update_profile`, guarded
# in `test_profile_write.py`, which is where the invocation guarantees live. The
# guarantee kept HERE is narrower and is about routes rather than intent:
#
#   `talent/profile`        (EP_PROFILE)         READ ONLY, in this server.
#   `talent/profile-upsert` (EP_PROFILE_UPSERT)  the write.
#
# They are different routes with different semantics and confusing them is the
# dangerous mistake. A POST to `talent/profile` carries a section-keyed SINGULAR
# envelope - one experience, one achievement - and pairs with a delete route. A
# POST to `talent/profile-upsert` carries `{field, value}` and REPLACES the whole
# field. Send a single skill to the second route thinking it behaves like the
# first and you have deleted sixty.
#
# The names make that easy to get wrong: `EP_PROFILE` is a literal substring of
# `EP_PROFILE_UPSERT`, so a naive grep matches both. This test caught exactly
# that collision in its own first version, which is the reason the matching
# below is anchored rather than a substring test.

_EP_PROFILE_RE = re.compile(r"\bEP_PROFILE\b(?!_)")


def test_the_plain_profile_route_is_only_ever_read():
    """`talent/profile` is this server's READ of him. It is never POSTed to.

    Uplers does expose a POST on it - the per-entity section upsert for
    experiences and achievements - and this server deliberately does not build
    that. If it ever does, it will be a separate, separately-guarded tool, and
    this test is what makes that a decision rather than a drift.
    """
    root = Path(__file__).resolve().parent.parent
    sources = [root / "server.py"] + sorted((root / "uplers_server").glob("*.py"))

    offences = []
    for source in sources:
        if source.name == "endpoints.py":
            continue
        for number, line in enumerate(source.read_text(encoding="utf-8").splitlines(), 1):
            if not _EP_PROFILE_RE.search(line) or line.strip().startswith("#"):
                continue
            if not ("get_json" in line or "EP_AUTH_PROBE" in line or "==" in line):
                offences.append("%s:%d  %s" % (source.name, number, line.strip()))

    assert offences == [], (
        "EP_PROFILE (the plain read route) is being used for something that is not a "
        "read. The write route is EP_PROFILE_UPSERT and it has different semantics:\n%s"
        % "\n".join(offences)
    )


def test_the_two_profile_routes_are_never_confused_for_each_other():
    """They are different URLs, and the difference is replacement vs upsert."""
    assert endpoints.EP_PROFILE != endpoints.EP_PROFILE_UPSERT
    assert endpoints.EP_PROFILE_UPSERT.startswith(endpoints.EP_PROFILE)
    # The above is precisely why a substring grep is not safe here, and is
    # asserted so that a future rename that removes the trap also removes the
    # need for the anchored regex above.
    assert _EP_PROFILE_RE.search("EP_PROFILE_UPSERT") is None
    assert _EP_PROFILE_RE.search("endpoints.EP_PROFILE)") is not None


# --- the counts the tool actually prints -----------------------------------


async def test_the_comparison_reports_the_real_uplers_counts_not_zero(
    monkeypatch, make_profile, real_payload
):
    """THE harmful sentence, pinned as numbers rather than as wording.

    The test above forbids the WORDS ("thinner", "platform.uplers.com"). This
    one forbids the STATE that produced them: a comparison that reads his
    Uplers profile as smaller than the local cache. Wording can be rewritten
    while the arithmetic underneath stays broken - that is exactly how "0
    skills there vs 32 here" was generated, from a shaper returning nothing
    and a comparator faithfully reporting it.

    Counts are asserted as exact integers from the captured record, and the
    ordering assertion (`uplers > local`) is the one that cannot be satisfied
    by a broken read.
    """
    make_profile(skills=["Node.js", "TypeScript", "AWS"])
    wire_talent(monkeypatch, serve(real_payload))

    result = await server.uplers_compare_profiles()

    assert result.uplers_skill_sections == {
        "skills": 61,
        "primary_skills": 56,
        "tools": 12,
        "distinct": 62,
    }
    assert result.uplers.skills == 62
    assert result.local.skills == 3
    assert result.uplers.skills > result.local.skills

    # The note he reads must carry the real number, not a floor or a hedge.
    assert "62 distinct skills" in " ".join(result.notes)


async def test_the_comparator_can_report_uplers_as_the_richer_side(
    monkeypatch, make_profile, real_payload
):
    """A comparator that can only recommend in one direction is a check that
    cannot fail.

    Both directions are exercised against the same captured record: a thin
    local profile must produce a large `only_uplers` and a local-side
    recommendation; a local profile that already carries every Uplers skill
    plus extras must produce an EMPTY `only_uplers` and must NOT recommend
    syncing. If the second case still recommended a sync, the tool would be
    emitting advice unconditionally rather than on evidence.
    """
    thin = talent_shape.to_talent_profile(real_payload)

    make_profile(skills=["Node.js"])
    wire_talent(monkeypatch, serve(real_payload))
    behind = await server.uplers_compare_profiles()

    assert len(behind.only_uplers) > 50
    assert "uplers_sync_profile_from_uplers" in (behind.recommendation or "")

    make_profile(skills=list(thin.all_skill_names()) + ["SMTP", "RabbitMQ"])
    wire_talent(monkeypatch, serve(real_payload))
    ahead = await server.uplers_compare_profiles()

    assert ahead.only_uplers == []
    assert sorted(ahead.only_local) == ["RabbitMQ", "SMTP"]
    assert ahead.uplers.skills == 62

    # It still points at `also=[...]` for the two contested fields, which is
    # correct and unrelated to skills. What it must NOT do is claim the local
    # copy is behind - that is the assertion with teeth, so it is made against
    # the skills claim specifically rather than against the whole string.
    assert "Skills are in sync" in (ahead.recommendation or "")
    assert "behind" not in (ahead.recommendation or "")
    assert not [note for note in ahead.notes if "MISSING from the local" in note]
