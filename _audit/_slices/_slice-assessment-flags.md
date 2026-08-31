SLICE: assessment flags (ai_needed / custom_screening_needed)
Date: 2026-08-23
Files created (the only two files written):
  D:\workspace\projects\job-hunting\mcp-servers\uplers\uplers_server\assessment_flags.py
  D:\workspace\projects\job-hunting\mcp-servers\uplers\tests\test_assessment_flags.py
No existing file was edited. No endpoint added. No network call. No commit.


1. MEASURED SHAPE OF BOTH FLAGS IN BOTH FIXTURES
------------------------------------------------
Measured with venv/Scripts/python.exe by recursive walk over the parsed JSON,
before any code was written.

DEPTH. Both fixtures are Laravel paginators. Rows live at payload["hrs"]["data"].
Both flags are plain TOP-LEVEL keys of each row, i.e. depth 1 relative to the
row, depth 3 relative to the envelope root (hrs -> data -> [i] -> flag).

TYPE. JSON boolean (Python bool) in every single observation. No int, no
string, no null, no absence.

COUNTS (exact, not estimated):

  fixture                rows  ai_needed                custom_screening_needed
  talent_feed.json         3   present 3/3, absent 0    present 3/3, absent 0
                               bool False x3            bool False x3
  talent_pipeline.json     9   present 9/9, absent 0    present 9/9, absent 0
                               bool False x9            bool False x9

  Total: 24 observations, 24 present, 24 of type bool, 24 with value False,
  0 true, 0 absent, 0 of any other type.

NESTING CHECK. On talent_pipeline the row is the APPLICATION and the
requisition hangs off row["hr"]. Checked on all 9 rows: the nested hr object
carries NEITHER flag (0/9 for each). So record.get("ai_needed") is correct for
both surfaces and no nesting logic is warranted. Pinned by
test_the_pipeline_nested_requisition_carries_neither_flag.

CROSS-CHECK. grep confirms these are the only two fixtures in tests/fixtures/
that mention either field, and grep across all .py confirms neither field was
read anywhere in the server before this slice.


2. DOES THE MEASUREMENT AGREE WITH THE "ALL 9 FALSE" FIGURE?
------------------------------------------------------------
YES. AGREEMENT, exactly and without qualification.

talent_pipeline.json holds 9 rows (per fixtures/MANIFEST.md these are his real
applications, "9 (all of them)"). All 9 carry ai_needed, all 9 read bool False.
The commissioned figure is reproduced. custom_screening_needed reads False on
the same 9 rows as well. No disagreement to report.


3. THE FINDING THAT BACKS THE CAVEAT (measured, on the same 9 rows)
------------------------------------------------------------------
custom_screening_needed is False on all 9 applications, yet the neighbouring
is_custome_screening (Uplers' own spelling) reads True on TWO of them, each
carrying a real custom_screening_at timestamp:

    2026-08-12 02:58:26
    2026-05-26 21:24:52

So the *_needed field and the is_* field are NOT the same fact. One is the
demand a requisition makes up front; the other records what actually happened
to that application. This is live-row evidence that these flags are PRE-APPLY
signal and not pipeline signal, and it is pinned by
test_two_real_applications_had_a_custom_screening_while_the_flag_reads_false.
Those neighbouring fields are deliberately NOT extracted by this slice.

Also measured, and used to justify the absent path: ai_mandatory is the integer
0 on all 3 feed rows and is ABSENT from all 9 pipeline rows. One field, two
surfaces, present-as-int against missing entirely. So absence is a real
phenomenon on these very rows even though it never happens to my two fields.

The required caveat appears in the module docstring AND in the docstrings of
both public functions, stating plainly that a low or zero count is pre-apply
demand, is not pipeline health, and must never be read as evidence that his
applications are fine. Both docstrings carry the surrounding numbers: 99 of 250
board requisitions demand an assessment (40%) and cleared reads 0 in
tests/fixtures/talent_assessments.json.


4. THE PUBLIC CONTRACT AS BUILT
--------------------------------
    def extract_flags(record: dict) -> dict
        -> {"ai_needed": True|False|None,
            "custom_screening_needed": True|False|None}
        Exactly two keys. None means NOT STATED (key absent, null, empty, or
        unreadable) and never means false.

    def summarise_flags(records: list) -> dict
        -> {"rows": int,
            "gated": int,                # rows where EITHER flag reads true
            "flags": {<flag>: {"true": n, "false": n,
                               "unknown": n, "unrecognised": n}},
            "unrecognised_values": [{"field": str, "value": str, "rows": int}]}
        Takes the ROW LIST (payload["hrs"]["data"]), not the envelope.
        Each flag's four buckets sum to "rows" exactly.

    def read_flag(record: dict, field: str) -> str        # supporting helper
        -> one of "true" / "false" / "unknown" / "unrecognised"

Both public functions are pure: no I/O, no network, no clock, no mutation of
the caller's rows (pinned by test_neither_function_mutates_the_row_it_was_given).

ABSENT vs FALSE is carried two ways. extract_flags returns None (tri-state);
summarise_flags keeps "unknown" and "false" as separate buckets. A fourth
bucket, "unrecognised", holds values the API stated but that cannot be read as
a boolean (a date string, a dict) and reports the raw repr in
unrecognised_values, deduped, rather than guessing. This exists because the API
is documented inconsistent: decimal strings like "5.00", integer 200 against
string "success" for one status field, and a date string in is_partner_company.

MEASURED OUTPUT on the real fixtures:
  talent_pipeline -> rows 9, gated 0, both flags {true 0, false 9, unknown 0,
                     unrecognised 0}, unrecognised_values []
  talent_feed     -> rows 3, gated 0, both flags {true 0, false 3, unknown 0,
                     unrecognised 0}, unrecognised_values []


5. CONTROL TESTS, BY NAME, AND WHAT EACH PROVES
------------------------------------------------
test_an_equality_assertion_cannot_catch_an_unnormalised_number__CONTROL
    Builds the exact bug (a "normaliser" returning int 1 and float 0.0) and
    shows `== True` / `== False` PASSING on it while `is True` / `is False` /
    `type(...) is bool` REJECT it. Proves every identity assertion in the file
    is the strong kind, and that the naive form could not have caught the bug.

test_a_get_with_a_false_default_would_collapse_the_two__CONTROL
    Shows record.get(field, False) returning the identical value for {} and
    for {"ai_needed": False}, and inventing False for the row that never
    carried the field. Then shows extract_flags returning None vs False.
    Proves the absent/false distinction is real and not a tautology.

test_the_summariser_counts_a_known_mix__CONTROL
    Hand-built 6-row list with counts known by construction: ai_needed 3 true /
    2 false / 1 absent, custom_screening_needed 1 true / 5 false, gated 4.
    Asserts the exact numbers. Proves the counter counts, since the two fixture
    summaries are all-false and would pass against a summariser hardwired to
    return zero for "true".

test_a_collapsing_summariser_would_miscount_the_same_rows__CONTROL
    Two rows state false, one never carried the field. Shows the obvious reader
    reporting 3 falses (named as the confident lie) against the real 2 false +
    1 unknown. Controls the "unknown" bucket specifically.

test_the_bucket_sum_can_actually_disagree__CONTROL
    Controls the four-buckets-sum-to-rows invariant, which would hold trivially
    if the summariser silently dropped rows it could not read; shows the 3-vs-4
    shape that such a summariser produces.

test_the_guards_still_admit_a_real_row__CONTROL
    Controls the three TypeError guards (envelope rejected, non-dict row
    rejected, non-dict record rejected). A guard that rejected everything would
    pass all three rejection tests and certify nothing; this pins the inputs
    that must NOT raise (a captured row, a one-row list, an empty list).

Additionally, the capture's LIMIT is asserted rather than described:
test_the_captures_cannot_exercise_true_unknown_or_unrecognised proves both
fixtures contain zero true, zero absent and zero drifted values for these two
fields. That is why the type matrix runs on small synthetic ROWS (no whole
payload is pasted in) and the file says so in its docstring instead of
pretending the capture covered those paths.


6. MUTATION EVIDENCE - EVERY GUARD SHOWN FAILING
-------------------------------------------------
The controls above are argued inline; this is the empirical check. Four
deliberate bugs were patched into the module in turn, the suite run against
each, then the module restored and verified byte-identical by sha256.

  M1  extract_flags returns the raw value (no normalisation)   -> RED (caught)
  M2  _to_bool returns False for unknown (absent collapses)    -> RED (caught)
  M3  plain truthiness for strings instead of a token table    -> RED (caught)
  M4  summariser drops rows it cannot classify                 -> RED (caught)

  restored byte-identical: True (sha256 4f452bd74b1c5ca4...)

4 of 4 caught. No mutation survived.


7. SUITE RESULT, AND A DISAGREEMENT WITH THE BRIEF'S BASELINE
--------------------------------------------------------------
My file alone:            63 passed.
Full suite with my file:  1103 passed, 1 failed.
Full suite ignoring mine: 1040 passed, 1 failed.
Delta: 1103 - 1040 = 63, exactly my file's contribution.

THE STATED BASELINE OF 983 NO LONGER HOLDS, and this is reported rather than
smoothed over. The tree is being written by sibling agents while this slice
ran: uplers_server/saved_filter.py (09:12), preference.py (09:14),
tests/test_saved_filter.py (09:16), uplers_server/outreach.py (09:17), and
tests/test_preference.py appeared between two of my own runs. An earlier
measurement in this same session implied a baseline of 985; twenty minutes
later the measured baseline was 1040. The number is moving because the repo is.

THE 1 FAILURE IS NOT MINE, verified three ways:
  * it is in tests/test_preference.py, against uplers_server/preference.py -
    two files I did not create and did not touch;
  * it reproduces with my file excluded from collection entirely (run B);
  * the control reads Path(preference.__file__) only, so it cannot reach my
    module, and grep confirms neither of my files contains the term it scans
    for.
It also RENAMED itself between my two runs
(test_nothing_in_this_module_mentions_the_nurture_route__control ->
test_the_nurture_route_is_named_only_as_a_warning_never_as_code__control),
which is direct evidence that agent is still editing it live. It is that
agent's in-flight work, not a regression from this slice.

Nothing was broken by this slice: every pre-existing test that passed before
still passes, and my 63 are additive.


8. HOUSE RULES
---------------
Strict ASCII verified by byte scan on both files: 0 bytes > 127 in each.
from __future__ import annotations in both. Long explanatory module docstrings
saying WHY. %-formatting in all error messages. No em-dashes, no smart quotes.
No file outside the two owned paths was written; git status confirms my only
entries are the two untracked files.
