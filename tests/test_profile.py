"""profile.py - the résumé parser and the profile store.

The profile is the input to every score in this server, so the tests that
matter most here are the ones about REFUSING: a missing résumé, an unreadable
file and an empty profile must all raise, because the alternative is scoring
235 requisitions against a blank and returning numbers that look real.
"""

from __future__ import annotations

import json

import pytest

from uplers_server import profile as prof

from conftest import RESUME_MARKDOWN


# --- résumé parsing -------------------------------------------------------


def test_parses_name_headline_years_location_and_skills():
    seed = prof.parse_resume_markdown(RESUME_MARKDOWN)

    assert seed["name"] == "Jane Doe"
    assert seed["headline"] == "Backend Software Engineer"
    assert seed["years_experience"] == 6.0
    assert seed["location"] == "Bangalore, India"
    assert "TypeScript" in seed["skills"]
    assert "Node.js" in seed["skills"]


def test_parenthesised_qualifiers_do_not_become_their_own_skills():
    """'AWS (S3, Lambda)' is one skill, not three."""
    seed = prof.parse_resume_markdown(RESUME_MARKDOWN)

    assert "AWS" in seed["skills"]
    assert "S3" not in seed["skills"]
    assert "Lambda" not in seed["skills"]


def test_missing_sections_are_absent_rather_than_guessed():
    seed = prof.parse_resume_markdown("# SOMEBODY\n\nNo sections at all.\n")

    assert seed["name"] == "Somebody"
    assert "skills" not in seed
    assert "location" not in seed
    assert "years_experience" not in seed


def test_category_labels_are_not_mistaken_for_skills():
    seed = prof.parse_resume_markdown(RESUME_MARKDOWN)

    assert "Programming Languages" not in seed["skills"]
    assert "Cloud & Infra" not in seed["skills"]


def test_the_operators_real_resume_still_parses(monkeypatch):
    """A regression guard on the file this server actually seeds from.

    Skipped rather than failed when the résumé is absent, because the parser
    is not broken by somebody checking out the repo without it.
    """
    from uplers_server import config

    path = config.DEFAULT_RESUME_PATH
    if not path.is_file():
        pytest.skip("no résumé at %s" % path)
    seed = prof.parse_resume_markdown(path.read_text(encoding="utf-8", errors="replace"))

    assert seed.get("years_experience")
    assert len(seed.get("skills") or []) >= 10


# --- persistence ----------------------------------------------------------


def test_load_returns_none_when_nothing_was_ever_set(isolated_profile):
    assert prof.load(path=isolated_profile) is None


def test_save_then_load_round_trips(isolated_profile):
    prof.save(prof.Profile(skills=["Node.js"], years_experience=4.0), path=isolated_profile)

    loaded = prof.load(path=isolated_profile)

    assert loaded.skills == ["Node.js"]
    assert loaded.years_experience == 4.0
    assert loaded.updated_at is not None


def test_save_leaves_no_temporary_file_behind(isolated_profile):
    prof.save(prof.Profile(skills=["Go"]), path=isolated_profile)

    siblings = list(isolated_profile.parent.glob("profile.json*"))

    assert [p.name for p in siblings] == ["profile.json"]


def test_corrupt_profile_raises_instead_of_falling_back(isolated_profile):
    isolated_profile.write_text("{not json", encoding="utf-8")

    with pytest.raises(prof.ProfileError) as exc:
        prof.load(path=isolated_profile)

    assert "silently fall back" in str(exc.value)


# --- seeding --------------------------------------------------------------


def test_seed_from_resume_writes_a_usable_profile(isolated_profile, resume_file):
    seeded = prof.seed_from_resume(resume=resume_file, path=isolated_profile)

    assert seeded.is_usable()
    assert seeded.source == "resume:Resume.md"
    assert json.loads(isolated_profile.read_text(encoding="utf-8"))["years_experience"] == 6.0


def test_seed_without_a_resume_raises_rather_than_returning_a_blank(isolated_profile):
    with pytest.raises(prof.ProfileError) as exc:
        prof.seed_from_resume(path=isolated_profile)

    assert "uplers_set_profile" in str(exc.value)


def test_seed_from_a_resume_with_no_usable_content_raises(isolated_profile, tmp_path):
    empty = tmp_path / "empty.md"
    empty.write_text("# NOBODY\n\nnothing here\n", encoding="utf-8")

    with pytest.raises(prof.ProfileError) as exc:
        prof.seed_from_resume(resume=empty, path=isolated_profile)

    assert "nothing to score against" in str(exc.value)


def test_load_or_seed_reports_whether_it_seeded(isolated_profile, resume_file, monkeypatch):
    monkeypatch.setattr(prof, "resume_path", lambda: resume_file)

    first, seeded_first = prof.load_or_seed(path=isolated_profile)
    second, seeded_second = prof.load_or_seed(path=isolated_profile)

    assert seeded_first is True
    assert seeded_second is False
    assert second.skills == first.skills


def test_require_refuses_a_profile_with_nothing_to_score_on(isolated_profile):
    prof.save(prof.Profile(name="Nobody"), path=isolated_profile)

    with pytest.raises(prof.ProfileError) as exc:
        prof.require(path=isolated_profile)

    assert "meaningless" in str(exc.value)


# --- small behaviours -----------------------------------------------------


def test_normalised_modes_accepts_any_casing_and_drops_junk():
    candidate = prof.Profile(preferred_modes=["remote", "HYBRID", "banana"])

    assert candidate.normalised_modes() == ["Remote", "Hybrid"]


def test_is_usable_needs_skills_or_experience():
    assert prof.Profile(skills=["Go"]).is_usable()
    assert prof.Profile(years_experience=1.0).is_usable()
    assert not prof.Profile(name="x").is_usable()


def test_the_status_vocabulary_is_exactly_what_the_tools_promise():
    assert prof.TRACK_STATUSES == (
        "interested",
        "applied_manually",
        "responded",
        "interviewing",
        "rejected",
        "closed",
    )
    assert set(prof.ACTIVE_STATUSES) < set(prof.TRACK_STATUSES)
    assert "rejected" not in prof.ACTIVE_STATUSES
    assert "closed" not in prof.ACTIVE_STATUSES
