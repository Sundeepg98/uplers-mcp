"""`groups` was capped at 20 and never said so. This is that cut, made visible.

WHAT WAS WRONG, and it was not a missing cap. `top_groups` has defaulted to 20
since this tool shipped and `search.market_stats` has always applied it. What
it never did was REPORT it: the payload carried 20 groups and nothing that
distinguished "these are all of them" from "these are 20 of 306". Measured on
the live 262-record index on 2026-08-25:

    group_by=role       returned 20 of  51 eligible  -  31 cut, silently
    group_by=skill      returned 20 of 306 eligible  - 286 cut, silently
    group_by=company    returned 20 of  53 eligible  -  33 cut, silently
    group_by=industry   returned 20 of  41 eligible  -  21 cut, silently

A default that drops something has to say it dropped it and name the flag that
brings it back, and 286 of 306 groups vanishing with nothing in the payload
saying so is the sharpest version of that rule this repo has.

THE NUMBER 20 IS DELIBERATELY UNCHANGED. Cutting it to hit a byte budget was
considered and ruled against: `server_info` is called incidentally, to check
whether a process is stale, where prose is pure tax - but `get_market_stats`
is called BECAUSE somebody asked for market statistics, and on a stats tool
the long tail is arguably the product. The silence was the bug; the number is
a preference. So this file asserts HONESTY, not size, and there is deliberately
no byte budget on this tool in tests/test_payload_budgets.py.

`min_group_size` was checked in the same pass and was already honest - it has
always reported its own drop in `notes`. That is pinned below so it stays so.
"""

from __future__ import annotations

from uplers_server import search


class TestTheCutIsReported:

    def test_a_truncated_answer_says_it_is_truncated(self, native_records):
        """groups_total > groups_returned is the whole signal."""
        stats = search.market_stats(
            native_records, group_by="skill", min_group_size=1, top_groups=3
        )

        assert stats.groups_returned == 3
        assert stats.groups_total > stats.groups_returned, (
            "the fixture cohort produced only %d groups, too few for "
            "top_groups=3 to cut anything - this test would certify nothing"
            % stats.groups_total
        )
        assert len(stats.groups) == stats.groups_returned

    def test_the_note_names_the_parameter_that_lifts_it(self, native_records):
        """Naming the flag is half the rule. A caller who cannot find the knob
        is in the same position as one who was never told."""
        stats = search.market_stats(
            native_records, group_by="skill", min_group_size=1, top_groups=3
        )

        note = " ".join(stats.notes)
        assert "top_groups" in note, stats.notes
        assert str(stats.groups_total) in note, stats.notes

    def test_an_untruncated_answer_reports_equal_counts(self, native_records):
        """The mirror case, and not decoration: if these were equal only when
        truncated, a caller could not read equality as "this is everything"."""
        stats = search.market_stats(
            native_records, group_by="currency", min_group_size=1, top_groups=100
        )

        assert stats.groups_total == stats.groups_returned
        assert not any("top_groups" in note for note in stats.notes), stats.notes

    def test_top_groups_zero_means_all(self, native_records):
        capped = search.market_stats(
            native_records, group_by="skill", min_group_size=1, top_groups=5
        )
        uncapped = search.market_stats(
            native_records, group_by="skill", min_group_size=1, top_groups=0
        )

        assert uncapped.groups_returned == uncapped.groups_total
        assert uncapped.groups_returned > capped.groups_returned

    def test_none_means_all_too(self, native_records):
        """`top_groups=None` is the other way a caller spells no cap, and it
        has to mean the same thing as 0 rather than raising on the slice."""
        stats = search.market_stats(
            native_records, group_by="skill", min_group_size=1, top_groups=None
        )

        assert stats.groups_returned == stats.groups_total

    def test_min_group_size_still_reports_its_own_drop(self, native_records):
        """The second silent cut that could have been sitting beside the one
        this file fixes. It was already honest; this keeps it that way."""
        stats = search.market_stats(
            native_records, group_by="skill", min_group_size=2, top_groups=0
        )

        note = " ".join(stats.notes)
        assert "min_group_size" in note, stats.notes

    def test_truncation_never_severs_a_group(self, native_records):
        """WHOLE OBJECTS ONLY. Truncation cuts the LIST, never into a member: a
        group with its `pay` block missing would read as a group with no pay
        data, which is a different and false claim."""
        full = search.market_stats(
            native_records, group_by="skill", min_group_size=1, top_groups=0
        )
        cut = search.market_stats(
            native_records, group_by="skill", min_group_size=1, top_groups=3
        )

        by_key = {group.key: group for group in full.groups}
        assert cut.groups, "nothing returned - the loop below would be vacuous"
        for group in cut.groups:
            assert group == by_key[group.key], (
                "group %r came back different when truncated" % group.key
            )

    def test_the_kept_groups_are_the_largest_and_the_order_is_unchanged(
            self, native_records):
        """The existing sort is (-count, key). This pins that truncation kept
        the FIRST n of that order rather than inventing a new one."""
        full = search.market_stats(
            native_records, group_by="skill", min_group_size=1, top_groups=0
        )
        cut = search.market_stats(
            native_records, group_by="skill", min_group_size=1, top_groups=4
        )

        assert [g.key for g in cut.groups] == [g.key for g in full.groups[:4]]


class TestTheseChecksCanFail:

    def test_the_completeness_check_would_catch_a_severed_group__CONTROL(
            self, native_records):
        """__CONTROL for test_truncation_never_severs_a_group, which compares
        objects for equality and would pass just as happily if every group
        were identical mush. This severs one and proves the comparison sees
        it."""
        full = search.market_stats(
            native_records, group_by="skill", min_group_size=1, top_groups=0
        )
        cut = search.market_stats(
            native_records, group_by="skill", min_group_size=1, top_groups=3
        )

        by_key = {group.key: group for group in full.groups}
        victim = cut.groups[0]
        victim.pay = None  # exactly the severing the test forbids

        assert victim != by_key[victim.key], (
            "a group stripped of its pay block compared EQUAL to the intact "
            "one - the completeness check certifies nothing"
        )

    def test_the_truncation_note_is_absent_when_nothing_is_cut__CONTROL(
            self, native_records):
        """__CONTROL for test_the_note_names_the_parameter_that_lifts_it. A
        note emitted unconditionally would pass that test while telling a
        caller their COMPLETE answer was truncated - the same lie pointed the
        other way."""
        stats = search.market_stats(
            native_records, group_by="currency", min_group_size=1, top_groups=0
        )

        assert stats.groups_total == stats.groups_returned
        assert not any("were cut by top_groups" in n for n in stats.notes), stats.notes
