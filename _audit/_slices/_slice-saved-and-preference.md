# Slice: saved-jobs filter contract + get-preference shaper

Date: 2026-08-23
Files created (four, nothing else touched):

- `D:\Sundeep\projects\job-hunting\mcp-servers\uplers\uplers_server\saved_filter.py`
- `D:\Sundeep\projects\job-hunting\mcp-servers\uplers\uplers_server\preference.py`
- `D:\Sundeep\projects\job-hunting\mcp-servers\uplers\tests\test_saved_filter.py`
- `D:\Sundeep\projects\job-hunting\mcp-servers\uplers\tests\test_preference.py`

No existing file was edited. No commit. No network call.


## 1. Signatures as built

### saved_filter.py

    saved_jobs_params(*, search: str | None = None, page: int = 1,
                      pagination: int = 20, **filters: Any) -> dict
    rejected_filters(requested: dict) -> list[str]
    assert_integer_one(params: dict) -> None
    read_saved_page(payload: Any) -> dict

    class SavedFilterRefused(ValueError)     # kind = "saved_filter_refused"

    SAVED_FILTER_ON = 1
    COMPATIBLE_FILTERS = frozenset({"search"})
    OUTSIDE_TERNARY = frozenset({"pagination", "page", "is_count", "activeJob"})
    KNOWN_DROPPED = ("roles", "locations", "experience", "engagements")

The two names the lead asked for are unchanged. `**filters` was added so the
refusal guard is REACHABLE: with only the three keyword-only parameters, a
caller could never express the illegal combination and the guard could never
be exercised or tested. A name in `OUTSIDE_TERNARY` passes through (the server
really does receive it); anything else raises `SavedFilterRefused` naming it,
instead of Python's own "unexpected keyword argument", which says nothing
about why the combination is meaningless.

`assert_integer_one` is a shipped function rather than a test-local helper on
purpose: the tests run the SAME instrument against a known-bad input to prove
it can fail. `read_saved_page` was added because the brief requires the zero
case to render as a sentence rather than as an error.

### preference.py

    shape_preference(payload: dict) -> dict
    master_index(payload: Any) -> dict[str, dict[str, str]]
    resolve(master: str | None, raw: Any,
            index: dict[str, dict[str, str]],
            given_label: Any = None) -> dict | None

    UNRESOLVED = "UNRESOLVED"

Pure: no I/O, no network, no clock, plain dict out, input never mutated
(asserted). A resolved entry is
`{"id", "label", "resolved", "master", "given_label"}`.


## 2. Contract facts pinned (all measured, with the receipt)

### saved-jobs filter (spec: `endpoints.QP_IS_SAVED_FILTER`, bundle chunk 8562)

1. The flag is the INTEGER 1, never the boolean `true` and never `"1"`.
   Pinned with `type(x) is int`, not `== 1`. `isinstance` would NOT
   discriminate either, because `bool` subclasses `int`.
2. The flag is EXCLUSIVE. `search` is allowed through; everything else is
   refused. The rejection rule is DENY BY DEFAULT, not an enumerated
   blocklist, because their branch is `1===t.is_saved_filter ? <saved> :
   Object.keys(t).map(...)` - any key their saved branch does not emit is
   dropped, including ones Uplers adds later. `KNOWN_DROPPED` is used only to
   parametrize tests and to write the message; it is not the definition.
3. `pagination`, `page`, `is_count`, `activeJob` sit outside the ternary and
   are accepted, not refused.

### response fixture `tests/fixtures/saved_filter_page.json` (live 2026-08-23)

4. `bookmarkedCount` is 0 and `hrs.data` is `[]` - he has ZERO platform-saved
   jobs. Rendered as a sentence naming both lists, not as an error.
5. The paginator carries NO `total` and NO `last_page`. The exact key set is
   asserted, `has_more` is derived from `next_page_url` alone, and the shaped
   dict carries `total_pages_known: False`.
6. `per_page` arrives as the STRING `"20"` and is coerced to `20`.
7. `from` and `to` are BOTH null on the empty page, so the obvious
   `to - from + 1` would raise on the only response ever captured; the
   returned count comes from `len(data)`.

### get-preference fixture `tests/fixtures/talent_preference.json` (live 2026-08-23)

8. Envelope is exactly `{masters, snooze, talent}`; `masters` holds 11 tables.
9. A master is NOT ordered by its own id: `jobSearchPreferenceMaster` runs
   values `[1, 3, 2]`. Position is not identity on this payload.
10. Ids cross a type divide: `job_search_preference` is the INTEGER 1,
    `preferred_method` is the STRING `"2"`, `company_type` is the STRING
    `"6"`; masters write `value` as an int. Both sides get `str()`.
11. `cities` keys its numeric id under `id`; the other ten masters key under
    `value`. In `cities`, `value` holds the city NAME. `_master_lookup`
    prefers `id` when a row carries one.
12. Unresolvable ids come back as `label == "UNRESOLVED"`, `resolved: False`,
    and are listed in the top-level `unresolved` roll-up - never `None`,
    never a fabricated label. NOT-SET is a different answer and stays `None`
    (his `availability` is null live).
13. No key matching `ctc|salary|compensation|resume|email|phone|contact`
    appears anywhere in the shaped tree, at any depth.


## 3. Control tests, by name, and what each proves

Every guard is paired with a control, and each control was SHOWN FAILING by a
mutation harness that patched the module object before pytest imported the
tests (harness in the session scratchpad; nothing on disk was mutated).

test_saved_filter.py

- `test_the_integer_check_actually_rejects_a_boolean__control`
  Runs `assert_integer_one` on `{is_saved_filter: True}`. Asserts FIRST that
  the naive `== 1` passes on that input, then that the real check raises.
  Proves the two are not interchangeable. Mutation `flag_is_true` reddens
  `test_the_flag_is_the_integer_one_not_the_boolean`.
- `test_the_integer_check_also_rejects_the_string__control` - `"1"` and a
  missing key.
- `test_the_flag_serialises_to_1_and_not_to_true__control` - the wire form;
  also asserts the mistaken encoding is reachable, so the contrast is real.
- `test_search_rides_alongside_the_saved_filter__control`
  The refusal is NOT blanket. Without this, every refusal test above it would
  pass for the wrong reason - a function that rejects everything rejects
  `roles` too.
- `test_rejected_filters_is_empty_for_a_request_the_server_honours__control`
  A list that is never empty names nothing.
- `test_a_boolean_page_is_refused_too__control`
  `page=True` would silently build `page=1`. Asserts `True >= 1` alongside, so
  the guard is shown to be a type check and not `value >= 1`.
- `test_per_page_arrives_as_a_string_and_is_coerced__control`
  Asserts the RAW value is a `str` first, so the coercion is proven to be real
  work rather than a no-op on an int.

test_preference.py

- `test_the_resolver_selects_the_matching_row_not_the_first__control`
  `preferred_method` is `"2"`, whose row is at INDEX 1. Asserts the answer
  equals index 1's label and differs from index 0's, and asserts the two
  labels differ so the control still controls.
- `test_a_take_the_first_resolver_would_answer_differently_on_four_fields__control`
  Computes what `masters[table][0]` would have said for four fields across
  four tables and requires each to differ. This is the test that fails if the
  implementation were take-the-first. Mutation `resolver_takes_the_first`
  reddens 6 tests including both of these.
- `test_indexing_cities_by_value_would_not_resolve_his_city__control`
  Builds the value-keyed index (the shape `talent_shape.masters_index`
  builds - correctly, for the profile payload) and asserts `"277" not in` it,
  while the id-keyed one resolves to "Bengaluru". Mutation
  `cities_indexed_by_value` reddens 6 tests.
- `test_an_unresolved_id_is_never_none_and_never_a_real_looking_label__control`
  Asserts the marker is not None and is not any real label from that master,
  and then that the SAME field with a resolvable id returns a real label - so
  `UNRESOLVED` is not simply what the field always says. Mutation
  `unresolved_is_none` reddens 4 tests.
- `test_the_roll_up_is_empty_when_everything_resolves__control`
  Removes the two fields with no master and requires the roll-up to empty.
- `test_the_privacy_sweep_can_actually_fail__control`
  Plants `expected_ctc` and a nested-in-a-list `contact_number` and requires
  both to be found. Necessary because the capture was scrubbed at capture
  time, so the sweep over real output cannot fail on this input - which
  `test_the_capture_was_scrubbed_before_it_reached_the_repo__control` states
  outright rather than leaving as a reassuring pass. Mutation
  `leaks_a_private_key` reddens 3 tests.
- `test_the_nurture_route_is_named_only_as_a_warning_never_as_code__control`
  Walks the AST and checks every string literal that is NOT the module
  docstring for `fJ7` / `nurture`, then asserts the walker collected real
  literals and that the docstring STILL carries the warning. A plain substring
  grep would have forced the warning to be deleted to pass.

Mutation results, all reproducible:

    baseline                 56 passed
    flag_is_true              2 failed
    silently_drops_filters   11 failed
    per_page_not_coerced      1 failed
    resolver_takes_the_first  6 failed
    cities_indexed_by_value   6 failed
    unresolved_is_none        4 failed
    leaks_a_private_key       3 failed


## 4. Suite

    venv/Scripts/python.exe -m pytest tests/test_saved_filter.py tests/test_preference.py -q
      -> 56 passed   (27 saved_filter + 29 preference)

    venv/Scripts/python.exe -m pytest -q
      -> 1190 passed

    venv/Scripts/python.exe -m pytest -q --ignore=tests/test_saved_filter.py \
                                          --ignore=tests/test_preference.py
      -> 1134 passed

1190 - 1134 = 56, exactly this slice. No pre-existing test changed status.

All four files verified STRICT ASCII by byte-level decode (no em-dash, no
smart quotes, nothing above U+007F).


## 5. Surprises - read this part

**S1. The stated baseline is wrong, and it was wrong before I started.**
The brief says the baseline is 983 passed. Measured at slice start, before I
created any file: **985 passed in 40.80s**. A +2 discrepancy that predates
this slice. Flagging rather than assuming.

**S2. The repo moved under the slice. Two sibling test files landed while I
worked**, so the closing full-suite number cannot be compared to the opening
one: `tests/test_assessment_flags.py` (09:15) and `tests/test_outreach.py`
plus `uplers_server/outreach.py` (09:21-09:22). They account for
1134 - 985 = 149 tests. The `--ignore` run above is the reason the "I broke
nothing" claim still holds despite the drift.

**S3. A full-suite run reported 3 failures that were not real.** My first
closing run showed
`test_outreach.py::TestTheClockIsInjectedNeverRead::test_the_module_never_reads_a_clock`
and two siblings failing with a `NameError` at line 900. `test_outreach.py`
alone passed 86/86 immediately afterwards, and its mtime (09:22:43) falls
INSIDE that full-suite run: the sibling agent saved the file mid-collection.
A clean re-run is 1190 passed / 0 failed. Recording it because a wave lead
reading a CI log would otherwise attribute those three to this slice.

**S4. `talent_shape.masters_index` cannot be reused for this payload.** It
indexes every master by `row["value"]`. That is correct for the profile
payload, whose masters have no `id` - but this payload's `cities` table is
`{"id": 277, "label": "Bengaluru", "value": "Bengaluru"}`, so a value-keyed
index yields a name-to-name map and resolves NONE of his stored city ids,
silently. This is why `preference.py` has its own `_master_lookup` rather than
importing the existing one. I did not touch `talent_shape.py`; the divergence
is deliberate and is pinned by
`test_indexing_cities_by_value_would_not_resolve_his_city__control`. Worth a
lead decision on whether the two should be reconciled later.

**S5. `preferred_modes` has no master table in this payload.** It is `[1, 3]`
and `masters` ships nothing for it. Cross-reference recorded but NOT acted on:
`tests/fixtures/talent_profile.json` carries the same two ids as
`[{"value": 1, "label": "Full time"}, {"value": 3, "label": "Contract"}]` -
engagement type, not work mode. That mapping comes from a DIFFERENT response
and this one cannot prove it, so nothing was imported and the ids come back
`UNRESOLVED`. Note `talent_shape._work_mode_preference` already records that
conflating Uplers' `preferred_modes` with a Remote/Hybrid/Office field
corrupts mode filters, so hardcoding would have been actively dangerous.

**S6. `user_journey_status.sub_statuses` also has no named master.** His
status is 2 ("actively_applying") and `activelyApplyingJobBoardsMaster` is in
the same payload, which makes a status-SELECTED sub-master plausible (ids 2
and 6 would then be "Naukri" and "Company Career Sites", which fits what is
known about him). That is a HYPOTHESIS and is labelled as one in the module
docstring, not resolved. Testing it needs a second capture taken while his
journey status is a different value.

**S6b. ESCALATION - P0, NOT ACTED ON, NEEDS THE LEAD.** The brief states the
preference fixture "has already had pay and contact fields deleted". That is
true of the WORKING COPY only. It is NOT true of git.

`tests/fixtures/talent_preference.json` is committed at `fa22b49`
("feat(session): declare the renewal mechanism...", 2026-08-23 08:54:30
+0530) carrying his real data:

    "current_ctc":   "1650000"
    "expected_ctc":  "2400000"
    "monthly_salary": 2400
    "ctc_breakdown":  null
    "original_resume": null
    "ra_profile_pic_url": ""
    "ra_resume_url": "https://platform.uplers.com/api/app/file/download/
                      resume/<his full name> CV <id>.pdf"

The scrub exists only as an UNCOMMITTED working-tree deletion of those 8
lines (` M tests/fixtures/talent_preference.json`), applied after the commit.

`git branch -r --contains fa22b49` returns `origin/master`, and
`git log origin/master..HEAD` is EMPTY - **the commit is pushed**. Remote is
`https://github.com/Sundeepg98/uplers-mcp.git`. I could not check repo
visibility without a network call, which this slice is forbidden to make;
`Sundeepg98/naukri-mcp` is public, so the question is not academic.

Not acted on, deliberately: remediating means rewriting history on `master`
and force-pushing, which is three separate things this slice is forbidden to
do, and it is a decision that belongs to the operator, not to an implementer.
Handing it up untouched.

Consequence inside my own scope: the test that sweeps the capture is named
`test_the_capture_on_disk_carries_no_pay_or_contact_key__control` and its
docstring states the scope explicitly. The earlier draft was named
"...was_scrubbed_before_it_reached_the_repo", which asserted something the
git history contradicts; renamed rather than left to read as a clean bill.

**S7. The privacy regex does not catch `resme_last_update`.** The field is
spelled without the "u" in Uplers' own payload, so `resume` does not match it.
It is not emitted, but anyone extending the shaper should know the regex would
not have stopped it.

**S8. One master label in the fixture is not ASCII** (company type 6 contains
U+2014). Source files stay strict ASCII because the test reads that label from
the fixture at runtime rather than typing it out; the shaper emits it
unchanged, which is data, not source.


## 6. Wiring notes for the lead

- Nothing here is registered in `server.py`. Both modules are standalone and
  importable; no tool calls them yet.
- `saved_jobs_params` is for `GET talent/hr/opportunities` (`EP_OPPORTUNITIES`).
  `is_count` and `activeJob` are deliberately NOT emitted - their values were
  never captured, and a guessed value is a different request. `OUTSIDE_TERNARY`
  names them so a caller with a real value can pass one through, and
  `test_is_count_and_active_job_are_not_emitted_by_default` keeps that a
  decision rather than an oversight.
- `SavedFilterRefused` subclasses `ValueError` (following `alerts.AlertError`)
  rather than `UplersError`, to keep `saved_filter.py` importable without
  pulling in the httpx client. Say the word if it should hang off
  `UplersError` instead.
- `shape_preference` emits 23 top-level keys, asserted as a whole by
  `test_the_shaper_emits_exactly_the_documented_field_set`, so any addition is
  a deliberate edit to that list.
- `snooze` crosses the boundary as a COUNT only. The live list is empty, so
  its row shape is unknown, and passing unknown rows through would be a hole
  in the privacy guarantee.
