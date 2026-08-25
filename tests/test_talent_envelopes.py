"""One requisition, four envelopes - and the score a blank one must refuse to give.

Everything here is driven by the four captured AUTHENTICATED payloads in
`tests/fixtures/`, taken live on 2026-08-22 by `scripts/capture_talent_rows.py`.
Not one input in this file is invented, and that is the whole point of the file
existing: the bugs it pins were all found by a live sweep and MISSED by a green
suite, because the suite's authenticated inputs were public-catalogue records
with a few session flags pasted on. A record built that way agrees with the
reader by construction.

THE BUG THIS FILE EXISTS FOR. The four surfaces spell the same two fields
differently, and the shaper knew only the catalogue's spelling:

    surface     job node        title                company
    catalogue   the row         RequestForTalent     CompanyName (top level)
    feed        the row         RequestForTalent     company.company_name
    pipeline    row["hr"]       hr.RequestForTalent  hr.company.company_name
    tailor      the row         title                company (a bare STRING)

So `uplers_my_pipeline` returned his nine REAL applications with title, company,
role, mode, notice and experience all absent, and `uplers_my_feed` returned
`company: None` on every row - the one field this server's own instructions call
its unique value, "the END CLIENT COMPANY NAME, which job boards hide".

AND THE WORSE HALF. A row shaped from the wrong node is not merely empty, it is
SCOREABLE: every field the scorer reads comes back None, jobcore falls back to
its unknown-defaults, and all nine of his applications returned an identical
`score: 50, verdict: partial`. A fabricated number on his real pipeline is worse
than a blank one, because it looks like an answer. Hence the second half of this
file: an Opportunity with no skills AND no experience band must REFUSE to score.

CONTROLS - each of the five new guards, reverted, with the measured damage.
Run as `pytest -p ctl_<name>` with a plugin containing only the line shown.
RE-MEASURED 2026-08-25 against the whole suite (1706 passing); the 2026-08-22
column is the original reading against an 886-test suite, kept so the drift is
visible rather than quietly overwritten:

                                                          08-22   08-25
    ctl_descent   shaping.job_view = lambda raw: raw          5       6
    ctl_company   shaping.company_name = lambda raw: raw.get("CompanyName") or None
                                                              6       7
    ctl_guard     fit.unscorable_reason = lambda opp: None     2       2
    ctl_diag      talent_shape._empty_diary_diagnosis = lambda meta: []
                                                              2       3
    ctl_basis     fit.score_basis = lambda opp: None           1       4

EVERY NUMBER THAT MOVED, MOVED UP, which is what a growing suite should do to a
real control - a control whose damage count FALLS is the one to investigate.
`ctl_basis` 1 -> 4 and `ctl_descent` 5 -> 6 are the row-relevance pass of
2026-08-25 (tests/test_row_relevance.py) binding onto the same two guards;
`ctl_company` 6 -> 7 is that pass asserting no row lost its end-client name to a
byte budget. `ctl_diag` 2 -> 3 predates it and was simply stale.

`ctl_guard` costing only 2 is not a weak control, it is the honest number: with
the descent repaired, nothing in a real payload is unscorable any more. The
guard is the BACKSTOP for the next envelope change, not the fix for this one,
and its two tests are the only ones that construct the empty case deliberately.
"""

from __future__ import annotations

import pytest

from uplers_server import fit, shaping, talent_shape
from uplers_server.models import Opportunity

from conftest import (
    TALENT_FEED,
    TALENT_INTERVIEWS,
    TALENT_PIPELINE,
    TALENT_TAILOR,
    load_talent_fixture,
)


def pipeline_rows() -> list[dict]:
    return load_talent_fixture(TALENT_PIPELINE)["hrs"]["data"]


def feed_rows() -> list[dict]:
    return load_talent_fixture(TALENT_FEED)["hrs"]["data"]


def tailor_rows() -> list[dict]:
    return load_talent_fixture(TALENT_TAILOR)["data"]


# --- the descent ----------------------------------------------------------


def test_a_pipeline_row_is_shaped_from_the_job_it_nests_not_from_the_wrapper():
    """His real application HR170725123514, read off the live capture.

    The wrapper row carries his application state; the requisition itself sits
    one level down under `hr`. Reading the wrapper finds no title and no
    company, because neither key is on it.
    """
    raw = pipeline_rows()[0]
    assert raw["HR_Number"] == "HR170725123514"
    assert "RequestForTalent" not in raw, "the wrapper must not sprout the key"
    assert raw["hr"]["RequestForTalent"] == "Software Developer - Backend(Remote)"

    opp = shaping.to_opportunity(raw)
    assert opp.title == "Software Developer - Backend(Remote)"
    assert opp.company == "A Series B Funded Innovative Device Trade-In Company - Netherlands"
    assert opp.mode_of_work == "Remote"
    assert opp.min_years_experience == 4.0
    assert opp.max_years_experience == 6.0
    assert opp.joining_period == "Immediately"
    assert opp.skills.must_have or opp.skills.good_to_have


def test_every_real_application_gets_a_title_and_a_company():
    """All nine, not just the one that was looked at."""
    rows = pipeline_rows()
    assert len(rows) == 9
    shaped = [shaping.to_opportunity(raw) for raw in rows]
    assert [opp.title for opp in shaped].count(None) == 0
    assert [opp.company for opp in shaped].count(None) == 0
    assert shaped[1].company == "Dino Ventures"
    assert shaped[8].title == "Backend Developer Nodejs"


def test_the_feed_spells_the_end_client_under_the_company_object():
    """`CompanyName` is absent on this tier; the name is nested."""
    raw = feed_rows()[0]
    assert "CompanyName" not in raw
    assert raw["company"]["company_name"] == "Building Autonomous AI for GCCs"
    opp = shaping.to_opportunity(raw)
    assert opp.title == "Senior Full-Stack Engineer"
    assert opp.company == "Building Autonomous AI for GCCs"


def test_no_feed_row_loses_the_end_client_name():
    """Including the aggregated row - `CompanyName` is absent on all three, so
    an aggregated posting lost its company name for the same reason a native
    one did."""
    rows = feed_rows()
    assert [raw.get("CompanyName") for raw in rows] == [None, None, None]
    shaped = [shaping.to_opportunity(raw) for raw in rows]
    assert [opp.company for opp in shaped] == [
        "Building Autonomous AI for GCCs",
        "EkamApps",
        "SourcingXPress",
    ]
    assert shaped[2].is_native is False


def test_the_tailor_surface_sends_a_bare_string_company_and_a_lowercase_title():
    """The one surface that renames both fields AND changes `company`'s type."""
    raw = tailor_rows()[0]
    assert raw["title"] == "Senior Full-Stack Engineer"
    assert isinstance(raw["company"], str)
    opp = shaping.to_opportunity(raw)
    assert opp.title == "Senior Full-Stack Engineer"
    assert opp.company == "Building Autonomous AI for GCCs"
    # A bare string is not an object, so nothing may be read OFF it.
    assert opp.industry is None


def test_the_tailor_surface_states_experience_as_a_sentence():
    """"3 - 5 Years of Exp" is a band, and dropping it costs the whole
    experience component of every tailored row's score."""
    opp = shaping.to_opportunity(tailor_rows()[0])
    assert opp.min_years_experience == 3.0
    assert opp.max_years_experience == 5.0


def test_a_test_requisition_is_recognised_through_the_wrapper_too():
    """`is_test_hr` describes the requisition, so on the nesting surface it
    would arrive under `hr`. No live list payload carries the key today, which
    is exactly why a wrapper-only read would have stayed silently dead."""
    raw = pipeline_rows()[0]
    assert "is_test_hr" not in raw and "is_test_hr" not in raw["hr"]
    assert talent_shape.is_test_record(raw) is False

    nested = {**raw, "hr": {**raw["hr"], "is_test_hr": 1}}
    assert talent_shape.is_test_record(nested) is True
    # and the unnested surfaces keep working exactly as before
    assert talent_shape.is_test_record({"is_test_hr": 1}) is True


def test_the_public_catalogue_spelling_still_wins_where_it_is_present(fixture_record):
    """The fix must not cost the tier it was already right about."""
    opp = shaping.to_opportunity(fixture_record("HR290626125252"))
    assert opp.title == "Sr. Test Automation Analyst"
    assert opp.company == "Precisely"


# --- what the wrapper itself is for ---------------------------------------


def test_the_wrapper_carries_when_he_applied_and_uplers_own_match_score():
    """Both were dropped. `matchmake_score` is Uplers' independent verdict on
    the same job this server scores, which makes it worth reading next to ours
    rather than instead of it."""
    row = talent_shape.to_talent_row(pipeline_rows()[0])
    assert row.applied_at == "13th Aug 2026"
    assert row.uplers_match_score == pytest.approx(84.15)
    assert row.uplers_status == "Added"


def test_a_row_whose_wrapper_reports_neither_says_so_with_none():
    row = talent_shape.to_talent_row(pipeline_rows()[1])
    assert row.applied_at == "12th Aug 2026"
    assert row.uplers_match_score is None


# --- the fabricated 50 ----------------------------------------------------


BLANK = Opportunity(hr_number="HR000000000000")


def test_an_opportunity_with_nothing_to_score_on_refuses_rather_than_returning_50(
    make_profile,
):
    """The headline. jobcore's two base components each fall back to 50 when
    their input is missing, so a record carrying neither skills nor an
    experience band produces a confident-looking 50 out of no evidence at all.
    """
    profile = make_profile()
    assert fit.unscorable_reason(BLANK)
    with pytest.raises(fit.UnscorableOpportunity):
        fit.assess(BLANK, profile)


def test_one_scoreable_input_is_enough_to_score(make_profile):
    """The guard fires on NOTHING, not on THIN. A tailored row has no skills
    and does have a band, and it must still get a number."""
    profile = make_profile()
    opp = shaping.to_opportunity(tailor_rows()[0])
    assert not opp.skills.must_have and not opp.skills.good_to_have
    assert fit.unscorable_reason(opp) is None
    assessment = fit.assess(opp, profile)
    assert isinstance(assessment["overall_score"], int)
    assert any("no skills" in flag for flag in assessment["flags"])


def test_a_score_resting_half_on_a_default_says_so_on_the_row(make_profile):
    """Found by the live proof of the fix above, and the same disease wearing a
    different number: with the descent repaired, all five tailored rows scored
    an identical 80, because `tailor-jobs` publishes no skill list and 60% of
    every one of those 80s was jobcore's neutral 50."""
    profile = make_profile()
    rows = [talent_shape.to_talent_row(raw, profile=profile) for raw in tailor_rows()]
    assert all(row.score is not None for row in rows)
    assert all(row.score_basis and "no skill list" in row.score_basis for row in rows)


def test_a_row_scored_on_real_data_carries_no_basis_caveat(make_profile):
    """The caveat must be absent when it does not apply, or it is noise that
    teaches a reader to ignore it."""
    profile = make_profile()
    row = talent_shape.to_talent_row(pipeline_rows()[0], profile=profile)
    assert row.score is not None
    assert row.score_basis is None


def test_his_nine_applications_do_not_all_score_the_same_number(make_profile):
    """The symptom exactly as the live sweep saw it: nine identical 50s.

    Nine real applications to nine different companies cannot all be an
    identical partial match, and a scorer that says they are is describing its
    own defaults rather than the jobs.
    """
    profile = make_profile()
    rows = [
        talent_shape.to_talent_row(raw, profile=profile) for raw in pipeline_rows()
    ]
    scores = [row.score for row in rows]
    assert None not in scores
    assert len(set(scores)) > 1, "all nine scored %r" % scores[0]


def test_a_row_that_cannot_be_scored_reports_no_score_rather_than_dying(make_profile):
    """A list surface must not lose eight good rows to one unscoreable one, and
    must not paper over it either."""
    profile = make_profile()
    row = talent_shape.to_talent_row({"HR_Number": "HR000000000000"}, profile=profile)
    assert row.score is None
    assert row.verdict is None
    assert row.unscorable


# --- the empty that could not explain itself ------------------------------


def test_an_empty_interview_list_reports_why_it_is_empty():
    """`{count: 0}` alone cannot distinguish "no interviews" from "the Gmail
    scan was never consented to". The raw envelope says which, in `meta`."""
    payload = load_talent_fixture(TALENT_INTERVIEWS)
    assert payload["data"] == []
    assert payload["meta"]["has_consent"] is False
    assert payload["meta"]["gmail_connected"] is True

    interviews, notes = talent_shape.interviews_from(payload)
    assert interviews == []
    joined = " ".join(notes).lower()
    assert "consent" in joined
    assert any("interviews" in note.lower() for note in notes)


def test_the_empty_diary_never_tells_him_to_go_and_switch_the_scan_on():
    """The note used to end "Turn the scan on in Uplers' own settings", and
    that instruction could cause the harm it was warning about.

    MEASURED 2026-08-24 (`_audit/_slices/_slice-consent-semantics.md`): the
    consent this flag names has no control anywhere in Uplers' shipped product
    - `consent_interview_email_scan` has zero readers in their whole bundle and
    the enable/revoke UI exists only as CSS. So the switch he would actually
    have found in settings is the Gmail JOB scan, a DIFFERENT consent that is
    currently ON and producing 79 jobs. Following the old advice meant hunting
    for a missing control and plausibly revoking a working, paid-for one.

    This is a regression guard, not a style check: it fails on the imperative,
    which is the part that moved him to act.
    """
    payload = load_talent_fixture(TALENT_INTERVIEWS)
    _, notes = talent_shape.interviews_from(payload)
    joined = " ".join(notes).lower()

    for instruction in (
        "turn the scan on",
        "turn it on",
        "switch the scan on",
        "enable the scan",
        "consent to the scan",
    ):
        assert instruction not in joined, (
            "the empty-diary note tells him to enable a scan that has no "
            "control in Uplers' product: %r" % instruction
        )

    # And it must still say the two things that ARE true, so the fix cannot be
    # "delete the note".
    assert "unresolved" in joined
    assert "uplers_email_scan" in joined


def test_the_mailbox_address_is_never_surfaced():
    """`meta.gmail_email` is his email. Reporting whether a mailbox is
    connected is diagnostic; reporting which one is a disclosure."""
    payload = load_talent_fixture(TALENT_INTERVIEWS)
    payload["meta"]["gmail_email"] = "someone@example.com"
    _, notes = talent_shape.interviews_from(payload)
    assert "example.com" not in " ".join(notes)
