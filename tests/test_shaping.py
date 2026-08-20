"""shaping.py - projecting the raw 112-field record onto the typed models.

Every expected value below was read out of the captured fixtures, so a change
in shaping that "looks fine" but drops a field will fail here.
"""

from __future__ import annotations

import pytest

from uplers_server import config, ids, shaping

from conftest import (
    AGENTAI,
    AGGREGATED,
    ANOMALY,
    CONFIDO,
    GOFORMA,
    NATIVE_IDS,
    PRECISELY,
    load_fixture,
)


# --- html_to_text ---------------------------------------------------------


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("<p>Hello <b>world</b> &amp; friends</p><p>Second</p>", "Hello world & friends\n\nSecond"),
        ("Line one<br>Line two<br/>Line three", "Line one\nLine two\nLine three"),
        ("<div>A</div><div></div><div></div><div>B</div>", "A\n\nB"),
        ("<ul><li>one</li><li>two</li></ul>", "one\n\ntwo"),
        ("plain &lt;text&gt; here", "plain <text> here"),
        ("<h2>Title</h2><p>Body</p>", "Title\n\nBody"),
    ],
)
def test_html_to_text_flattens_markup(raw, expected):
    assert shaping.html_to_text(raw) == expected


def test_nbsp_unescapes_to_a_hard_space_and_is_not_collapsed():
    # Documented behaviour, not an accident: the whitespace collapse runs on
    # ASCII blanks only, so &nbsp; survives as U+00A0 in the flattened text.
    assert shaping.html_to_text("a &nbsp; b") == "a " + chr(160) + " b"


@pytest.mark.parametrize("empty", [None, "", "   ", "<p></p>", "<br><br>"])
def test_html_to_text_returns_none_for_nothing(empty):
    assert shaping.html_to_text(empty) is None


# --- numeric coercion -----------------------------------------------------


@pytest.mark.parametrize(
    "value, expected",
    [("5.00", 5.0), ("0.00", 0.0), (3, 3.0), (2.5, 2.5), ("", None), (None, None), ("abc", None)],
)
def test_to_float(value, expected):
    assert shaping.to_float(value) == expected


@pytest.mark.parametrize("flag", [True, False])
def test_booleans_never_become_numbers(flag):
    # bool is an int subclass; True must not silently read as 1.0 years.
    assert shaping.to_float(flag) is None
    assert shaping.to_int(flag) is None


def test_to_int_truncates_a_decimal_string():
    assert shaping.to_int("10.00") == 10
    assert shaping.to_int("junk") is None


# --- pay band -------------------------------------------------------------


@pytest.mark.parametrize(
    "cost, expected",
    [
        ("9,00,000-15,00,000", (900000, 1500000)),
        ("Confidential", (None, None)),
        ("549", (549, 549)),
        (12345, (None, None)),
        (None, (None, None)),
    ],
)
def test_parse_local_band(cost, expected):
    assert shaping.parse_local_band(cost) == expected


def test_upto_grammar_states_a_ceiling_with_no_floor():
    raw = load_fixture(CONFIDO)
    # Pin the premise before pinning the behaviour.
    assert raw["cost"] == "30,00,000"
    assert raw["cost_string"] == " Upto INR 30,00,000 / year"

    pay = shaping.build_pay(raw)
    assert pay.local_min is None
    assert pay.local_max == 3000000
    assert pay.currency == "INR"
    assert pay.text == "Upto INR 30,00,000 / year"


def test_a_real_band_keeps_both_ends():
    pay = shaping.build_pay(load_fixture(AGENTAI))
    assert (pay.local_min, pay.local_max) == (60000, 90000)
    assert (pay.usd_year_min, pay.usd_year_max) == (60000, 90000)
    assert pay.confidential is False


@pytest.mark.parametrize(
    "hr_number, expected_period",
    [
        (GOFORMA, "month"),
        (AGENTAI, "year"),
        (CONFIDO, "year"),
        (PRECISELY, None),
        (AGGREGATED, None),
    ],
)
def test_pay_period_distinguishes_monthly_contract_quotes(hr_number, expected_period):
    raw = load_fixture(hr_number)
    assert shaping.pay_period(raw["cost_string"]) == expected_period
    assert shaping.build_pay(raw).local_period == expected_period


def test_confidential_budget_is_flagged():
    assert shaping.build_pay(load_fixture(PRECISELY)).confidential is True
    assert shaping.build_pay(load_fixture(CONFIDO)).confidential is False


# --- experience -----------------------------------------------------------


def test_max_yoe_zero_means_no_upper_bound_not_zero_years():
    raw = load_fixture(AGGREGATED)
    assert raw["max_yoe"] == "0.00"
    assert shaping.to_float(raw["max_yoe"]) == 0.0  # the raw value really is zero
    assert shaping.to_opportunity(raw).max_years_experience is None


def test_a_real_max_yoe_survives():
    opp = shaping.to_opportunity(load_fixture(CONFIDO))
    assert opp.max_years_experience == 10.0
    assert opp.min_years_experience == 5.0


# --- skills, company, assessments ----------------------------------------


def test_build_skills_splits_must_have_from_good_to_have():
    skills = shaping.build_skills(load_fixture(AGENTAI))
    assert len(skills.must_have) == 6
    assert len(skills.good_to_have) == 5
    assert "Python" in skills.must_have
    assert "Django" in skills.good_to_have
    assert "Python" not in skills.good_to_have


def test_build_skills_handles_an_all_must_have_record():
    skills = shaping.build_skills(load_fixture(AGGREGATED))
    assert len(skills.must_have) == 5
    assert skills.good_to_have == []


def test_company_name_prefers_the_end_client_over_the_anonymised_blurb():
    raw = load_fixture(PRECISELY)
    # The nested name is a generic descriptor; the top-level one is the client.
    assert raw["company"]["company_name"] == "Global leader in data integrity"
    assert raw["CompanyName"] == "Precisely"

    company = shaping.build_company(raw)
    assert company.name == "Precisely"
    assert company.industry == "SAAS"
    assert company.website == "https://www.precisely.com/"


def test_company_name_falls_back_to_the_nested_name_when_top_level_is_missing():
    assert shaping.build_company({"company": {"company_name": "Nested Ltd"}}).name == "Nested Ltd"
    assert shaping.build_company({"CompanyName": "", "company": {}}).name is None


def test_company_about_is_flattened_and_capped():
    company = shaping.build_company(load_fixture(GOFORMA))
    assert "<" not in company.about
    assert len(company.about) <= config.COMPANY_ABOUT_PREVIEW_CHARS + 4


def test_build_assessments_reads_a_populated_list():
    assessments = shaping.build_assessments(load_fixture(CONFIDO))
    assert len(assessments) == 1
    assert assessments[0].name == "AiInterview"
    assert assessments[0].tool == "AiInterview"
    assert assessments[0].duration == "30 Mins"  # the payload carries " 30 Mins"
    assert assessments[0].difficulty is None


def test_build_assessments_is_empty_when_the_record_has_none():
    assert load_fixture(AGENTAI)["assessments"] == []
    assert shaping.build_assessments(load_fixture(AGENTAI)) == []


def test_build_shift_reads_the_first_shift_window():
    shift = shaping.build_shift(load_fixture(GOFORMA))
    assert shift.timezone == "(GMT+01:00) Europe/London (BST)"
    assert shift.start_time == "9:30 AM"
    assert shift.end_time == "1:30 PM"
    assert shift.ist_window == "2:00PM to 6:00PM"


# --- native vs aggregated (group A) --------------------------------------


def test_aggregated_fixture_is_not_native():
    assert shaping.to_opportunity(load_fixture(AGGREGATED)).is_native is False


@pytest.mark.parametrize("hr_number", NATIVE_IDS)
def test_every_native_fixture_is_native(hr_number):
    assert shaping.to_opportunity(load_fixture(hr_number)).is_native is True


def test_is_native_comes_from_the_record_field_not_the_id_length():
    """Regression guard: the 13-digit anomaly is a REAL Uplers requisition.

    ids.classify() can only guess from the digit count and says "unknown";
    the record's own is_aggregator_job field says native, and that wins.
    """
    raw = load_fixture(ANOMALY)
    assert ids.classify(ANOMALY) == "unknown"
    assert raw["is_aggregator_job"] is False
    assert shaping.to_opportunity(raw).is_native is True


# --- whole-row projection -------------------------------------------------


def test_to_opportunity_projects_the_headline_fields():
    opp = shaping.to_opportunity(load_fixture(CONFIDO))
    assert opp.hr_number == CONFIDO
    assert opp.title == "Graphic Designer"
    assert opp.role == "Graphic designer"
    assert opp.company == "Confido Health"
    assert opp.industry == "Hospital & Healthcare"
    assert opp.mode_of_work == "Hybrid"
    assert opp.city == "Bengaluru"
    assert opp.joining_period == "15 Days"
    assert opp.availability == "Full Time"
    assert opp.duration_type == "Long Term"
    assert opp.assessments_required == 1
    assert opp.talents_count == 666
    assert opp.posted_at == "2025-07-10T00:19:19"
    assert opp.created_at == "2025-07-09T19:07:33.000000Z"
    assert opp.url == "https://platform.uplers.com/talent/all-opportunities/" + CONFIDO


def test_posted_at_is_none_when_the_id_carries_no_timestamp():
    assert shaping.to_opportunity(load_fixture(AGGREGATED)).posted_at is None
    assert shaping.to_opportunity(load_fixture(ANOMALY)).posted_at is None


def test_to_detail_adds_the_decision_fields():
    detail = shaping.to_detail(load_fixture(PRECISELY))
    assert detail.hiring_model == "Hire a Contractor"
    assert detail.positions_open == 1
    assert detail.experience_flexible is False
    assert detail.company_info.name == "Precisely"
    assert detail.shift.ist_window == "10:00AM to 7:00PM"
    assert len(detail.assessments) == 1


def test_to_detail_reads_the_hybrid_office_visit_cadence():
    detail = shaping.to_detail(load_fixture(CONFIDO))
    assert detail.office_visit_frequency == "2-3 times a week"
    assert detail.status_note is None  # HR_Status is "" in this record


def test_long_description_is_truncated_by_default_and_whole_on_request():
    raw = load_fixture(AGGREGATED)  # the only fixture longer than the preview cap
    preview = shaping.to_detail(raw, full_description=False)
    whole = shaping.to_detail(raw, full_description=True)

    assert len(whole.description) == 4916 > config.DESCRIPTION_PREVIEW_CHARS
    assert whole.description_truncated is False
    assert preview.description_truncated is True
    assert preview.description.endswith(" ...")
    assert len(preview.description) < len(whole.description)
    assert len(preview.description) <= config.DESCRIPTION_PREVIEW_CHARS + 4
    assert whole.description.startswith(preview.description[:200])


def test_short_description_is_never_truncated():
    raw = load_fixture(GOFORMA)
    preview = shaping.to_detail(raw, full_description=False)
    assert len(preview.description) == 2272 < config.DESCRIPTION_PREVIEW_CHARS
    assert preview.description_truncated is False
    assert preview.description == shaping.to_detail(raw, full_description=True).description
