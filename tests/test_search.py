"""search.py - filtering, sorting and market aggregation over cached records.

The filter tests run against the real captured records so the expected values
are the ones a user would actually see; the sort and percentile tests use
hand-built records so the expected order is unambiguous.
"""

from __future__ import annotations

import pytest

from uplers_server import search
from uplers_server.shaping import to_opportunity

from conftest import (
    AGENTAI,
    AGGREGATED,
    ANOMALY,
    CONFIDO,
    GOFORMA,
    PRECISELY,
    load_fixture,
)


def opp(hr_number):
    return to_opportunity(load_fixture(hr_number))


def _raw(hr_number, **fields):
    """A minimal API-shaped record: only the fields a test actually pins."""
    record = {"HR_Number": hr_number}
    record.update(fields)
    return record


# Three hand-built records with unambiguous ordering on every sort key.
# The ids decode to 2026-01-01 / -02 / -03.
ROW_A = _raw(
    "HR010126120000",
    cost_start_in_dollar_yearly="10000",
    cost_end_in_dollar_yearly="20000",
    talents_count=500,
)
ROW_B = _raw(
    "HR020126120000",
    cost_start_in_dollar_yearly="30000",
    cost_end_in_dollar_yearly="40000",
    talents_count=10,
)
ROW_C = _raw(
    "HR030126120000",
    cost_start_in_dollar_yearly="5000",
    cost_end_in_dollar_yearly="6000",
    talents_count=100,
)
THREE_ROWS = [ROW_A, ROW_B, ROW_C]


# --- skill / title / company ---------------------------------------------


def test_skill_matches_either_list_case_insensitively():
    agentai = opp(AGENTAI)
    assert "Python" in agentai.skills.must_have
    assert "Django" in agentai.skills.good_to_have

    assert search.matches(agentai, skill="python") is True     # must-have, lowercased
    assert search.matches(agentai, skill="DJANGO") is True     # good-to-have, uppercased
    assert search.matches(agentai, skill="cobol") is False


def test_skill_search_spans_both_lists_across_the_cohort(all_records):
    results, matched, scanned = search.search_records(all_records, skill="hubspot")
    assert scanned == 6
    assert matched == 2  # GoForma and Mavlers, both as a good-to-have
    assert sorted(o.hr_number for o in results) == sorted([GOFORMA, ANOMALY])


def test_title_matches_the_job_title():
    assert search.matches(opp(CONFIDO), title="graphic") is True
    assert search.matches(opp(CONFIDO), title="backend") is False


def test_title_also_matches_the_normalised_role():
    precisely = opp(PRECISELY)
    # The word appears ONLY in Uplers' normalised role, not in the job title.
    assert precisely.title == "Sr. Test Automation Analyst"
    assert precisely.role == "Sr. Marketing Automation Specialist"
    assert "marketing" not in precisely.title.lower()

    assert search.matches(precisely, title="marketing") is True


def test_company_matches_the_end_client_name():
    assert search.matches(opp(AGENTAI), company="agentai") is True
    assert search.matches(opp(AGENTAI), company="Databricks") is False


# --- experience -----------------------------------------------------------


def test_min_and_max_yoe_bound_the_roles_own_minimum():
    precisely = opp(PRECISELY)
    assert precisely.min_years_experience == 4.0

    assert search.matches(precisely, min_yoe=4) is True
    assert search.matches(precisely, min_yoe=5) is False
    assert search.matches(precisely, max_yoe=4) is True
    assert search.matches(precisely, max_yoe=3) is False


def test_yoe_admits_is_a_band_overlap_test():
    agentai = opp(AGENTAI)                 # 3 - 6 years
    databricks = opp(AGGREGATED)           # 15 years and up

    assert (agentai.min_years_experience, agentai.max_years_experience) == (3.0, 6.0)
    assert search.matches(agentai, yoe_admits=5) is True
    assert search.matches(agentai, yoe_admits=2) is False   # under the floor
    assert search.matches(agentai, yoe_admits=7) is False   # over the ceiling

    assert databricks.min_years_experience == 15.0
    assert search.matches(databricks, yoe_admits=5) is False


def test_a_role_with_no_stated_ceiling_admits_anyone_above_its_floor():
    """The subtlest rule in the file: max_yoe "0.00" is NO upper bound."""
    mavlers = opp(ANOMALY)
    assert load_fixture(ANOMALY)["max_yoe"] == "0.00"
    assert mavlers.min_years_experience == 4.0
    assert mavlers.max_years_experience is None

    assert search.matches(mavlers, yoe_admits=4) is True
    assert search.matches(mavlers, yoe_admits=100) is True   # no ceiling to exceed
    assert search.matches(mavlers, yoe_admits=3) is False    # the floor still binds


# --- mode of work / currency ---------------------------------------------


def test_remote_only_and_mode_of_work_agree_and_ignore_case():
    remote = opp(AGENTAI)
    hybrid = opp(CONFIDO)
    assert (remote.mode_of_work, hybrid.mode_of_work) == ("Remote", "Hybrid")

    assert search.matches(remote, remote_only=True) is True
    assert search.matches(remote, mode_of_work="remote") is True
    assert search.matches(remote, mode_of_work="REMOTE") is True

    assert search.matches(hybrid, remote_only=True) is False
    assert search.matches(hybrid, mode_of_work="remote") is False
    assert search.matches(hybrid, mode_of_work="hybrid") is True


def test_currency_is_case_insensitive_but_exact():
    goforma = opp(GOFORMA)
    assert goforma.pay.currency == "GBP"

    assert search.matches(goforma, currency="gbp") is True
    assert search.matches(goforma, currency="GBP") is True
    assert search.matches(goforma, currency="INR") is False
    assert search.matches(goforma, currency="GB") is False  # exact, not substring


# --- pay ------------------------------------------------------------------


def test_min_pay_filters_on_the_top_of_the_band():
    agentai = opp(AGENTAI)
    assert (agentai.pay.usd_year_min, agentai.pay.usd_year_max) == (60000, 90000)

    assert search.matches(agentai, min_pay_usd_year=90000) is True
    assert search.matches(agentai, min_pay_usd_year=90001) is False
    # 70000 is inside the band, and the band top clears the floor, so it stays.
    assert search.matches(agentai, min_pay_usd_year=70000) is True


def test_records_with_no_usd_figures_are_ADMITTED_by_a_pay_floor(all_records):
    """Unknown pay is not the same as pay below the floor.

    This asserted the opposite until 2026-08-20, and it was wrong. 111 of the
    235 native requisitions - 47% - are confidential-budget, and the profile
    field's own contract reads "Roles below it are flagged, not hidden". A
    floor that dropped the unknowns would silently remove a large slice of the
    board while reporting a clean result.

    A figure BELOW the floor is still excluded. A figure that is ABSENT is
    admitted, and carries the "no USD band published, pay unverifiable" flag
    from blockers_and_flags so it is never silently mixed in with verified
    ones.
    """
    databricks = opp(AGGREGATED)
    assert (databricks.pay.usd_year_min, databricks.pay.usd_year_max) == (None, None)
    assert search.matches(databricks, min_pay_usd_year=1) is True
    # However high the floor: still unknown, still not evidence of being below.
    assert search.matches(databricks, min_pay_usd_year=10**9) is True

    results, matched, scanned = search.search_records(all_records, min_pay_usd_year=1)
    assert scanned == 6
    assert matched == 6
    assert AGGREGATED in [o.hr_number for o in results]


def test_a_confidential_budget_is_still_compared_on_its_published_figure():
    """"Confidential" hides the band from the CLIENT's listing, not from
    Uplers' own normalisation - all 111 confidential native reqs carry one."""
    precisely = opp(PRECISELY)
    assert precisely.pay.confidential is True
    assert (precisely.pay.usd_year_min, precisely.pay.usd_year_max) == (25731, 29974)

    assert search.matches(precisely, min_pay_usd_year=29974) is True
    assert search.matches(precisely, min_pay_usd_year=29975) is False


# --- the pay floor is currency-blind because Uplers converted already -------


def test_an_inr_band_is_compared_on_uplers_own_usd_normalisation():
    """No exchange rate is applied by this server, and none should be.

    Uplers publishes `cost_*_in_dollar_yearly` for every requisition whatever
    the local currency - measured 2026-08-20: 179 INR, 53 USD, 2 AUD, 1 GBP,
    and all 235 carry the USD figure. So an INR band and a USD band are
    already commensurable and a single USD floor compares both correctly.

    Applying an assumed rate on top would be the bug: at the ~Rs 88/USD rate
    one might reach for, Rs 20,00,000 reads as $22,727, while Uplers' own
    August-2026 normalisation of that exact band is $20,959 - so the assumed
    rate would quietly turn a Rs 20 LPA floor into a Rs 21.7 LPA one.
    """
    confido = opp(CONFIDO)
    assert confido.pay.currency == "INR"
    assert confido.pay.text.strip() == "Upto INR 30,00,000 / year"
    assert confido.pay.usd_year_max == 35081

    # A Rs 30 LPA role clears a Rs 20 LPA floor under either reading of it.
    assert search.matches(confido, min_pay_usd_year=20959) is True     # Uplers' rate
    assert search.matches(confido, min_pay_usd_year=22700) is True     # ~Rs 88/USD

    # A GBP band goes through the identical comparison and is excluded on its
    # own merits, not on its currency.
    goforma = opp(GOFORMA)
    assert goforma.pay.currency == "GBP"
    assert goforma.pay.usd_year_max == 8867
    assert search.matches(goforma, min_pay_usd_year=20959) is False

    # As does a USD-denominated one.
    agentai = opp(AGENTAI)
    assert agentai.pay.currency == "USD"
    assert search.matches(agentai, min_pay_usd_year=20959) is True


def test_uplers_normalises_at_the_rate_of_the_posting_date_not_todays():
    """The one place a rupee floor expressed in dollars is inexact, stated
    rather than hidden.

    Uplers converts once, at the FX rate current when the requisition was
    posted, and never re-normalises. Measured across the 100 INR reqs with a
    parseable annual band (2026-08-20), the implied rate runs from 85.5 on
    mid-2025 postings to 95.4 on August-2026 ones, with 59 of the 100 at
    94.9-95.4.

    So ANOMALY's Rs 18,00,000 ceiling, converted in November 2024 at ~82.9,
    reads as $21,726 - ABOVE a $20,959 floor derived from an August-2026
    Rs 20,00,000 band. The error is one-directional and it is the safe
    direction: an old, slightly-underpaying role is admitted rather than a
    qualifying one being hidden. Recent postings, which are the ones worth
    applying to, convert exactly.
    """
    anomaly = opp(ANOMALY)
    assert anomaly.pay.currency == "INR"
    assert anomaly.pay.text == "INR 15,00,000-18,00,000 / year"
    assert anomaly.pay.usd_year_max == 21726
    implied_rate = 1_800_000 / 21_726
    assert 82.0 < implied_rate < 83.5          # ~82.9, a 2024 rate

    assert search.matches(anomaly, min_pay_usd_year=20959) is True


def test_an_inr_role_at_25_lpa_survives_a_22700_floor():
    """The specific case a naive rate would get wrong.

    The USD figures are Uplers' own: requisition HR140826172010 in the live
    index reads "INR 20,00,000-25,00,000 / year" and is normalised to
    $20,959-$26,198. Both a Rs 20 LPA floor read as $20,959 and one read as
    $22,700 admit it, because the comparison is against a real published
    dollar figure rather than a rate this server invented.
    """
    twenty_five_lpa = to_opportunity(
        _raw(
            "HR140826172010",
            Currency="INR",
            cost_string="INR 20,00,000-25,00,000 / year",
            cost_start_in_dollar_yearly="20959",
            cost_end_in_dollar_yearly="26198",
        )
    )
    assert twenty_five_lpa.pay.currency == "INR"
    assert twenty_five_lpa.pay.usd_year_max == 26198

    assert search.matches(twenty_five_lpa, min_pay_usd_year=22700) is True
    assert search.matches(twenty_five_lpa, min_pay_usd_year=20959) is True
    # And it is not admitted unconditionally - a floor above the band's top
    # still excludes it.
    assert search.matches(twenty_five_lpa, min_pay_usd_year=26199) is False


# --- notice period --------------------------------------------------------


@pytest.mark.parametrize(
    "text, expected",
    [
        ("30 Days", 30),
        ("15 Days", 15),
        ("Immediately", 0),
        ("immediate", 0),
        ("2 Months", 60),
        ("3 weeks", 21),
        (None, None),
        ("", None),
        ("asap", None),
    ],
)
def test_notice_days(text, expected):
    assert search.notice_days(text) == expected


def test_min_notice_days_drops_immediate_joiners_and_keeps_a_month():
    immediate = opp(PRECISELY)
    fifteen = opp(CONFIDO)
    thirty = opp(ANOMALY)
    assert (immediate.joining_period, fifteen.joining_period, thirty.joining_period) == (
        "Immediately",
        "15 Days",
        "30 Days",
    )

    assert search.matches(immediate, min_notice_days=15) is False
    assert search.matches(fifteen, min_notice_days=15) is True
    assert search.matches(thirty, min_notice_days=15) is True


def test_joining_period_is_a_substring_filter():
    assert search.matches(opp(CONFIDO), joining_period="15 Days") is True
    assert search.matches(opp(CONFIDO), joining_period="30") is False


# --- sorting and limits ---------------------------------------------------


@pytest.mark.parametrize(
    "sort, expected_ids",
    [
        ("newest", ["HR030126120000", "HR020126120000", "HR010126120000"]),
        ("oldest", ["HR010126120000", "HR020126120000", "HR030126120000"]),
        ("pay_desc", ["HR020126120000", "HR010126120000", "HR030126120000"]),
        ("pay_asc", ["HR030126120000", "HR010126120000", "HR020126120000"]),
        ("least_competition", ["HR020126120000", "HR030126120000", "HR010126120000"]),
    ],
)
def test_every_supported_sort_orders_as_documented(sort, expected_ids):
    assert sort in search.SORTS
    results, _, _ = search.search_records(THREE_ROWS, sort=sort)
    assert [o.hr_number for o in results] == expected_ids


def test_all_five_sorts_are_covered_by_the_parametrisation():
    assert set(search.SORTS) == {
        "newest",
        "oldest",
        "pay_desc",
        "pay_asc",
        "least_competition",
    }


def test_unknown_sort_falls_back_to_newest_without_raising():
    results, _, _ = search.search_records(THREE_ROWS, sort="by_vibes")
    assert [o.hr_number for o in results] == [
        "HR030126120000",
        "HR020126120000",
        "HR010126120000",
    ]


def test_limit_truncates_results_but_matched_reports_the_true_total():
    results, matched, scanned = search.search_records(THREE_ROWS, limit=2)
    assert len(results) == 2
    assert matched == 3
    assert scanned == 3
    assert [o.hr_number for o in results] == ["HR030126120000", "HR020126120000"]


def test_scanned_counts_every_record_even_when_none_match():
    results, matched, scanned = search.search_records(THREE_ROWS, skill="nothing-like-this")
    assert results == []
    assert matched == 0
    assert scanned == 3


# --- market stats (group G) ----------------------------------------------


def test_group_by_currency_over_the_native_cohort(native_records):
    stats = search.market_stats(native_records, group_by="currency", min_group_size=1)

    assert stats.group_by == "currency"
    assert stats.population == 5
    assert [(g.key, g.count) for g in stats.groups] == [("INR", 3), ("GBP", 1), ("USD", 1)]


def test_including_the_aggregated_record_grows_the_inr_group(all_records):
    stats = search.market_stats(all_records, group_by="currency", min_group_size=1)
    assert [(g.key, g.count) for g in stats.groups] == [("INR", 4), ("GBP", 1), ("USD", 1)]
    assert stats.population == 6


def test_min_group_size_drops_small_groups_and_records_how_many(native_records):
    stats = search.market_stats(native_records, group_by="currency", min_group_size=2)

    assert [(g.key, g.count) for g in stats.groups] == [("INR", 3)]
    assert any("2 group(s) below min_group_size=2" in note for note in stats.notes)


def test_currency_group_figures_are_computed_from_the_real_records(native_records):
    stats = search.market_stats(native_records, group_by="currency", min_group_size=1)
    inr = [g for g in stats.groups if g.key == "INR"][0]

    # Confido 35081/35081, Precisely 25731/29974, Mavlers 18105/21726
    assert inr.pay.n_with_pay == 3
    assert inr.pay.usd_year_min_p25 == 18105
    assert inr.pay.usd_year_min_median == 25731
    assert inr.pay.usd_year_min_p75 == 35081
    assert inr.pay.usd_year_max_median == 29974
    assert inr.pay.usd_year_overall_low == 18105
    assert inr.pay.usd_year_overall_high == 35081

    assert inr.median_min_yoe == 4.0
    assert inr.remote_share == 0.67          # 2 of 3 are Remote
    assert inr.currencies == {"INR": 3}
    assert list(inr.joining_periods) == ["15 Days", "30 Days", "Immediately"]
    assert inr.example_companies == ["Confido Health", "Mavlers", "Precisely"]
    assert len(inr.top_skills) == 8
    assert inr.top_skills == sorted(inr.top_skills)  # all tied at 1, so alphabetical


def test_percentiles_and_medians_on_a_population_with_known_values():
    population = [
        _raw(
            "HR0%d0126120000" % n,
            cost_start_in_dollar_yearly=str(n * 10000),
            cost_end_in_dollar_yearly=str(n * 10000 + 5000),
            YearOfExp="%d.00" % n,
            Currency="USD",
        )
        for n in (1, 2, 3, 4, 5)
    ]
    population.append(_raw("HR060126120000", Currency="USD"))  # no pay data at all

    stats = search.market_stats(population, group_by="currency", min_group_size=1)
    group = stats.groups[0]

    assert group.key == "USD"
    assert group.count == 6
    assert group.pay.n_with_pay == 5             # the pay-less record is excluded
    assert group.pay.usd_year_min_p25 == 20000
    assert group.pay.usd_year_min_median == 30000
    assert group.pay.usd_year_min_p75 == 40000
    assert group.pay.usd_year_max_median == 35000
    assert group.pay.usd_year_overall_low == 10000
    assert group.pay.usd_year_overall_high == 55000
    assert group.median_min_yoe == 3.0
    assert group.remote_share == 0.0


def test_unknown_group_by_falls_back_to_role(native_records):
    stats = search.market_stats(native_records, group_by="constellation", min_group_size=1)

    assert stats.group_by == "role"
    assert "Full Stack Engineer" in [g.key for g in stats.groups]
    assert "constellation" not in [g.key for g in stats.groups]


def test_role_grouping_falls_back_to_the_title_when_hr_role_is_null(native_records):
    stats = search.market_stats(native_records, group_by="role", min_group_size=1)
    keys = [g.key for g in stats.groups]
    # Mavlers has HR_Role null, so its job title stands in.
    assert "CRM Strategist (US Shift)" in keys


def test_overall_is_none_when_nothing_survives_the_filters(native_records):
    stats = search.market_stats(native_records, group_by="currency", currency="XYZ")

    assert stats.population == 0
    assert stats.groups == []
    assert stats.overall is None
    assert any("real zero, not a fetch failure" in note for note in stats.notes)


def test_overall_summarises_the_whole_filtered_population(native_records):
    stats = search.market_stats(native_records, group_by="currency", min_group_size=1)

    assert stats.overall.key == "ALL"
    assert stats.overall.count == 5
    assert stats.overall.currencies == {"INR": 3, "GBP": 1, "USD": 1}
    assert len(stats.overall.top_skills) == 15   # overall reports more skills than a group


def test_filters_narrow_the_population_before_aggregating(native_records):
    stats = search.market_stats(native_records, group_by="currency", remote_only=True, min_group_size=1)

    assert stats.population == 4   # every native but the Hybrid one
    assert sum(g.count for g in stats.groups) == 4
    assert stats.overall.remote_share == 1.0
