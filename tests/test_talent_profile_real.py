"""The profile tests that run against the REAL captured payload.

Every other profile test in this suite builds its own payload, and every one
of them writes a skill as ``{"name": "Node.js"}``. The live API has never sent
that shape. It sends a JOIN: `talent_details.skills` carries rows of
``{skill_id: 3898076, years_of_experience: "4", order: 0}`` and the human name
lives in a separate 176,329-row `masters.skills` lookup keyed by `value`.

So 667 tests passed while the extractor read ZERO skills off the real thing,
and `uplers_compare_profiles` told the operator his Uplers profile was empty
on the day he had just finished filling it in.

The lesson is not "add a test". It is that a hand-built payload can only ever
test the shape its author imagined. These tests read
`tests/fixtures/talent_profile.json`, captured live by
`scripts/capture_profile_fixture.py`, so they fail when the API changes rather
than when somebody's imagination does.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from uplers_server import talent_shape

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "talent_profile.json"


@pytest.fixture
def real_payload() -> dict:
    with FIXTURE.open(encoding="utf-8") as handle:
        return json.load(handle)


@pytest.fixture
def real_profile(real_payload):
    return talent_shape.to_talent_profile(real_payload)


# --- the bug ---------------------------------------------------------------


def test_the_real_payload_yields_skills_at_all(real_profile):
    """THE regression. Zero skills here was the whole bug.

    Asserted as a floor rather than an exact count, because he keeps editing
    his profile and this test is about the extractor working, not about how
    many skills he had on the day it was captured.
    """
    assert len(real_profile.skills) >= 50, (
        "The real payload resolved %d skills. Zero means the masters join is "
        "broken again." % len(real_profile.skills)
    )


def test_all_three_skill_bearing_sections_are_extracted_separately(real_profile):
    """`skills`, `primaryskills` and `tools` are three lists, not one.

    They mean different things to Uplers' matching, so collapsing them into a
    single `skills` field would throw away the distinction he would act on.
    """
    assert real_profile.skills
    assert real_profile.primary_skills
    assert real_profile.tools


def test_primary_skills_is_a_strict_subset_of_skills(real_profile):
    """MEASURED on the live record: 56 primaryskills, all 56 inside the 61.

    The two sections are the same underlying rows - identical row `id`s - with
    `primaryskills` filtered. Anything in primary but not in skills would mean
    that relationship has changed and the note this server prints about it has
    become a lie.
    """
    assert set(real_profile.primary_skills) <= set(real_profile.skills)
    assert len(real_profile.primary_skills) < len(real_profile.skills)


def test_every_skill_row_resolves_to_a_name_and_none_are_dropped(real_payload, real_profile):
    """A dropped row is invisible, which is exactly how this bug survived.

    Counting rows in against names out is the only check that fails loudly
    when a lookup miss starts silently discarding skills again.
    """
    rows = len(real_payload["talent_details"]["skills"])
    assert len(real_profile.skills) == rows
    assert real_profile.unresolved_skill_ids == []


def test_an_unresolvable_id_is_reported_and_never_silently_dropped(real_payload):
    """The module's own doctrine: report the miss rather than default it."""
    payload = json.loads(json.dumps(real_payload))
    payload["talent_details"]["skills"].append(
        {"id": 1, "skill_id": 999999999, "years_of_experience": "2", "order": 0}
    )

    result = talent_shape.to_talent_profile(payload)

    assert "999999999" in result.unresolved_skill_ids
    assert any("999999999" in note or "1 skill" in note for note in result.notes)


def test_skills_without_a_masters_lookup_fall_back_to_inline_names():
    """Not every caller has `masters`. A payload that names skills inline -
    the shape the rest of the suite builds - must still read."""
    payload = {
        "talent_details": {
            "full_name": "X",
            "skills": [{"name": "Node.js"}, {"name": "TypeScript"}],
        }
    }
    assert talent_shape.to_talent_profile(payload).skills == ["Node.js", "TypeScript"]


def test_the_resolver_selects_by_id_rather_than_taking_the_first_row(real_payload):
    """The fixture carries 40 uncited decoy skills for exactly this test.

    A resolver that zipped the two lists positionally would pass every count
    assertion above and return 61 wrong names.
    """
    result = talent_shape.to_talent_profile(real_payload)
    lookup = {
        str(row["value"]): row["label"] for row in real_payload["masters"]["skills"]
    }
    for row in real_payload["talent_details"]["skills"]:
        assert lookup[str(row["skill_id"])] in result.skills


def test_years_of_experience_per_skill_survives_the_join(real_profile):
    """Uplers records per-skill years. Dropping it loses real signal, and it
    is the only place his depth in a specific skill is written down."""
    assert real_profile.skill_years
    assert all(isinstance(value, float) for value in real_profile.skill_years.values())
    assert all(value > 0 for value in real_profile.skill_years.values())


# --- the sections that were being thrown away ------------------------------


def test_the_other_populated_sections_are_carried_through(real_profile):
    """Ten sections arrived in every payload and none of them were read."""
    assert real_profile.objective
    assert real_profile.preferred_cities
    assert real_profile.engagement_types
    assert real_profile.experiences
    assert real_profile.projects
    assert real_profile.educations
    assert real_profile.achievements
    assert real_profile.headline
    assert real_profile.years_experience
    assert real_profile.notice_period


def test_work_mode_preference_comes_from_preferred_method_not_preferred_modes(real_profile):
    """The trap. `preferred_modes` on Uplers is ENGAGEMENT type - "Full time",
    "Contract" - and reads exactly like the local profile's `preferred_modes`,
    which is Remote/Hybrid/Office. They are different fields.

    The Remote/Office answer lives in `preferred_method`, an integer resolved
    through `masters.preferredMethodMaster`. Mapping one onto the other would
    have written "Full time" into a work-mode field and silently corrupted
    every mode-based filter.
    """
    assert real_profile.work_mode_preference == "Remote or Office"
    assert "Full time" in real_profile.engagement_types
    assert real_profile.work_mode_preference not in real_profile.engagement_types


def test_experiences_carry_title_company_and_dates(real_profile):
    entry = real_profile.experiences[0]
    assert entry.title and entry.company
    assert entry.start_date


# --- the private half ------------------------------------------------------

#: Everything the operator named as never-print, plus the obvious neighbours.
FORBIDDEN = (
    "current_ctc",
    "expected_ctc",
    "monthly_salary",
    "dob",
    "contact_number",
    "whatsapp_optin",
    "address",
    "email",
    "profile_pic_url",
    "resume_url",
)

#: Value shapes that betray real private data wherever they appear. Deliberately
#: NOT a substring scan for the field names: "email" occurs four times in the
#: captured achievements ("restructured the bulk email scheduler") because bulk
#: email IS his professional domain, and a naive scan flags his CV as a leak.
#: A key name is checked as a key; a value is checked by shape.
_PRIVATE_VALUE_SHAPES = (
    (re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+"), "an email address"),
    (re.compile(r"(?<!\d)(?:\+91[-\s]?)?[6-9]\d{9}(?!\d)"), "an Indian mobile number"),
    (re.compile(r"https?://\S*(?:resume|cv|profile_pic|photo)\S*", re.I), "a personal file URL"),
)


def _walk_keys(node, trail=""):
    """Every key path in a nested structure, so a leak can be located."""
    if isinstance(node, dict):
        for key, value in node.items():
            yield ("%s.%s" % (trail, key), key, value)
            yield from _walk_keys(value, "%s.%s" % (trail, key))
    elif isinstance(node, list):
        for item in node:
            yield from _walk_keys(item, trail + "[]")


def test_the_captured_fixture_carries_none_of_the_private_fields(real_payload):
    """The fixture is committed, so a leak here is a leak in git history.

    Asserted on the raw file rather than the shaped result, because the shaper
    could start reading one of these tomorrow and this test would still hold
    the line at the point where it enters the repository.
    """
    leaked_keys = [
        trail for trail, key, _ in _walk_keys(real_payload) if key in FORBIDDEN
    ]
    assert leaked_keys == [], "private keys in the committed fixture: %s" % leaked_keys

    blob = json.dumps(real_payload)
    for pattern, described in _PRIVATE_VALUE_SHAPES:
        found = pattern.findall(blob)
        assert found == [], "the fixture contains %s: %s" % (described, found)


def test_no_private_field_can_reach_the_shaped_profile(real_payload):
    """The fixture cannot prove this on its own - it has them removed.

    So they are put BACK, with recognisable values, and the shaped result is
    searched for both the key names and the values. This is the test that
    fails if somebody adds `expected_ctc` to the model in six months.
    """
    payload = json.loads(json.dumps(real_payload))
    payload["talent_details"].update(
        {
            "current_ctc": "1800000",
            "expected_ctc": "2600000",
            "monthly_salary": "150000",
            "dob": "1999-01-31",
            "contact_number": "9876543210",
            "whatsapp_optin": 1,
            "address": "221B Baker Street, Bengaluru",
            "email": "someone@example.com",
            "profile_pic_url": "https://cdn.example.com/pic.png",
            "resume_url": "https://cdn.example.com/cv.pdf",
        }
    )

    shaped = talent_shape.to_talent_profile(payload).model_dump()
    rendered = json.dumps(shaped)

    # Key names are checked AS KEYS. A substring scan would flag his own
    # achievements, which say "the bulk email scheduler" four times, because
    # bulk email is his professional domain rather than a leak.
    leaked = [trail for trail, key, _ in _walk_keys(shaped) if key in FORBIDDEN]
    assert leaked == [], "private keys reached the shaped profile: %s" % leaked

    for value in (
        "1800000",
        "2600000",
        "150000",
        "1999-01-31",
        "9876543210",
        "221B Baker Street",
        "someone@example.com",
        "cdn.example.com",
    ):
        assert value not in rendered, "a private VALUE (%s) reached the output" % value


def test_sections_present_names_sections_without_quoting_their_values(real_payload):
    """`sections_present` is a list of key NAMES and must stay that way.

    A section name is diagnostic; a section value can be his salary. This
    pins the distinction so a future "make it more useful" change cannot
    quietly start emitting values.
    """
    payload = json.loads(json.dumps(real_payload))
    payload["talent_details"]["expected_ctc"] = "2600000"

    result = talent_shape.to_talent_profile(payload)

    assert all(isinstance(entry, str) for entry in result.sections_present)
    assert "2600000" not in json.dumps(result.sections_present)


# --- the count, not merely the presence ------------------------------------
#
# The tests above assert a FLOOR (">= 50") and per-section non-emptiness. Both
# would have passed while the number the operator actually reads was wrong,
# which is the failure mode that let this bug reach him twice. The number he
# reads is the DISTINCT UNION across the three sections - it is what
# `uplers_compare_profiles` prints and what `ProfileSummary.skills` carries -
# and until now nothing pinned it at all.
#
# These assert exact integers against the COMMITTED fixture. That is stable by
# construction: the fixture only moves when somebody re-captures it, and when
# they do, a failure here is the correct signal that the numbers moved rather
# than noise.

#: MEASURED on tests/fixtures/talent_profile.json, and on the live record it
#: was captured from (re-verified live 2026-08-21): 61 rows in `skills`, 56 in
#: `primaryskills`, 12 in `tools`, resolving to 62 distinct names.
FIXTURE_COUNTS = {"skills": 61, "primaryskills": 56, "tools": 12, "distinct": 62}


def test_each_section_resolves_its_exact_row_count(real_payload, real_profile):
    """Rows in, names out, per section - not just for `skills`.

    `tools` and `primaryskills` join through the same masters lookup on
    different foreign keys (`tool_id`, `skill_id`). A join that silently
    stopped matching on ONE of them would leave the other two populated, so
    every non-empty assertion in this file would still pass.
    """
    details = real_payload["talent_details"]
    for section, resolved in (
        ("skills", real_profile.skills),
        ("primaryskills", real_profile.primary_skills),
        ("tools", real_profile.tools),
    ):
        assert len(resolved) == len(details[section]) == FIXTURE_COUNTS[section], (
            "`%s` resolved %d name(s) from %d row(s); expected %d."
            % (section, len(resolved), len(details[section]), FIXTURE_COUNTS[section])
        )


def test_the_distinct_union_is_a_real_union_of_all_three_sections(real_profile):
    """THE number he reads, pinned to an integer.

    "0 skills there vs 32 here" was this number. Asserting it is non-zero, or
    above a floor, does not catch the case that matters: a union that quietly
    degrades to `len(skills)` and drops whatever `tools` alone contributes.
    So this pins the exact count AND asserts it strictly exceeds the largest
    single section, which is the property a collapsed union cannot satisfy.
    """
    distinct = real_profile.all_skill_names()

    assert len(distinct) == FIXTURE_COUNTS["distinct"]
    assert len(distinct) > len(real_profile.skills), (
        "The union (%d) is not larger than `skills` alone (%d), so `tools` is "
        "contributing nothing and the union has collapsed to one section."
        % (len(distinct), len(real_profile.skills))
    )
    assert len(set(name.lower() for name in distinct)) == len(distinct)
    # `CosmosDB` is the one name that lives ONLY under `tools` on this record
    # and it is the entire difference between 61 and 62 - so it is the single
    # skill whose disappearance proves the union stopped unioning.
    #
    # It survives the fold only because `skills` spells its near-twin "cosmos
    # Db", one space apart, so the two do not collide on a lowercased key.
    # `ClickHouse`/`Clickhouse` DOES collide and is correctly folded to one.
    # That pair is the reason this test names a specific skill rather than
    # trusting the arithmetic: the +1 is not whichever tool you would guess.
    assert "CosmosDB" in distinct
    assert "CosmosDB" not in real_profile.skills
    assert [name for name in real_profile.tools if name.lower() not in
            {skill.lower() for skill in real_profile.skills}] == ["CosmosDB"]
