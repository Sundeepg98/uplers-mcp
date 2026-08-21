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
  * NOTHING in this server may write to his Uplers profile. `uplers_apply` and
    `uplers_dismiss` write to Uplers and stay - they act on requisitions, not
    on him. The profile is read-only, permanently, and the last test in this
    file is what keeps it that way.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from test_talent_tools import serve, wire_talent, writes  # noqa: F401
from uplers_server import endpoints, profile as profile_mod
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


async def test_sync_makes_no_request_other_than_reading_the_profile(
    monkeypatch, make_profile, real_payload
):
    make_profile()
    calls = wire_talent(monkeypatch, serve(real_payload))

    await server.uplers_sync_profile_from_uplers(confirm=True)

    assert writes(calls) == []
    assert [call.url.path for call in calls] == ["/api/" + endpoints.EP_PROFILE]


# --- the standing guarantee ------------------------------------------------

#: Read as: this server may write to a REQUISITION, never to HIM.
PROFILE_WRITE_VERBS = ("post_json", "post_form", "put_json", "patch_json", "delete_json")


def test_no_source_path_anywhere_writes_to_the_uplers_profile():
    """A grep, as a test, because the guarantee is about absence.

    Absence cannot be demonstrated by exercising a code path - there is no path
    to exercise - so the source itself is the thing under test. Every write
    verb is located and the endpoint it targets is checked; EP_PROFILE must
    never be one of them.

    `uplers_apply` and `uplers_dismiss` legitimately POST, and they stay. They
    act on a requisition. This test is the line between the two.
    """
    root = Path(__file__).resolve().parent.parent
    sources = [root / "server.py"] + sorted((root / "uplers_server").glob("*.py"))

    offences = []
    for source in sources:
        for number, line in enumerate(source.read_text(encoding="utf-8").splitlines(), 1):
            if any(verb in line for verb in PROFILE_WRITE_VERBS) and "EP_PROFILE" in line:
                offences.append("%s:%d  %s" % (source.name, number, line.strip()))

    assert offences == [], (
        "a write to the operator's Uplers profile has appeared. His profile is "
        "authoritative and this server reads it only:\n%s" % "\n".join(offences)
    )


def test_the_profile_endpoint_is_only_ever_read():
    """The complement of the test above, from the other direction.

    Every line that mentions EP_PROFILE outside its own definition must be a
    GET or a comparison. This catches a write built through a helper whose name
    is not in PROFILE_WRITE_VERBS.
    """
    root = Path(__file__).resolve().parent.parent
    sources = [root / "server.py"] + sorted((root / "uplers_server").glob("*.py"))

    for source in sources:
        if source.name == "endpoints.py":
            continue
        for number, line in enumerate(source.read_text(encoding="utf-8").splitlines(), 1):
            if "EP_PROFILE" not in line or line.strip().startswith("#"):
                continue
            assert "get_json" in line or "EP_AUTH_PROBE" in line or "==" in line, (
                "%s:%d touches EP_PROFILE in a way that is not a read: %s"
                % (source.name, number, line.strip())
            )
