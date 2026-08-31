# Slice: outreach read-through (shaping layer only)

Built 2026-08-23. Files written, and nothing else touched:

    D:\workspace\projects\job-hunting\mcp-servers\uplers\uplers_server\outreach.py
    D:\workspace\projects\job-hunting\mcp-servers\uplers\tests\test_outreach.py

No edit to server.py, endpoints.py, talent*.py or any existing test. No commit.
No network call. No write path of any kind in the shipped module.

## 1. The six signatures as built

```python
def unwrap(payload: Any, *, route: str, expect: type = dict) -> Any
def shape_agent_plan(payload: dict, *, today: str | None = None) -> dict
def shape_agent_dashboard(payload: dict) -> dict
def shape_pending_jobs(payload: dict) -> dict
def shape_missed_followups(payload: dict, *, now: str | None = None) -> dict
def shape_activity(payload: dict) -> dict
def agent_readthrough(*, plan, dashboard, pending, missed, activity) -> dict
```

DEVIATION, deliberate and flagged: two shapers carry ONE EXTRA keyword-only
argument with a default, `today=` on the plan and `now=` on the missed
follow-ups. Your call sites `shape_agent_plan(payload)` and
`shape_missed_followups(payload)` are unchanged and still work; they just
return `days_remaining: None` / `age_days: None` plus a note that says a
reference date was never supplied.

The reason is your own constraint. You asked for days-remaining and staleness
"relative to a date PASSED IN or injected, never `datetime.now()`", and
`agent_readthrough` was specified to take the five ALREADY-SHAPED dicts, so the
clock cannot enter there without changing its signature. Injecting at shaping
time keeps `agent_readthrough` exactly the five keyword-only arguments you
named and keeps all six functions pure. If you would rather have the clock on
the read-through instead, it is a two-line move; say which and I will do it.

Also exported: `OutreachError(TalentError)` with `kind = "outreach_shape"`, so
every existing `except TalentError` in server.py already catches it and a shape
failure is never mistaken for an expired session.

Pinned by tests, with today = 2026-08-23 injected: `total_jobs_run 48`,
`positive 8`, `unseen 7`, `reminders 7`, `tailored 0`, `today_agent_runs 0`,
`jobs_in_queue 0`, `max_limit 8`, `interview_count 0`, missed `count 7` over
`days 15`, oldest reply waiting 12 days, plan 18 days remaining, activity
32 Completed / 16 Failed over 42 companies, 11 of the 16 failures naming
LinkedIn in Uplers' own words.

## 2. The envelope idioms, measured

Measured by reading the five fixtures, not assumed:

    talent/outreach/outreach-step                     "status": "success"  STRING
    talent/outreach/get-outreach-dashboard-data       "status": 200        INTEGER
    talent/outreach/pending-jobs                      "status": 200        INTEGER
    talent/outreach/missed-positive-reply-followups   "status": 200        INTEGER
    talent/outreach/agent-tailor-activity             "status": 200        INTEGER

One tolerant unwrapper accepts exactly those two values through the module
constant `SUCCESS_VALUES = ("success", 200)`, read at call time so a test can
narrow it. It REFUSES, loudly and by route name, on five separate conditions:
payload not a JSON object; no `status` key; a status outside the two measured
idioms; no `data` key; `data` not the container that route was measured to send.

`1` is REFUSED here even though `endpoints.SUCCESS_NUMERIC` records it, because
it was measured on a different route and accepting an unmeasured value to be
helpful is how the guard stops guarding. Booleans are refused explicitly
(`True == 1` in Python).

Container shapes measured: `data` is a dict on four routes, and a LIST on
pending-jobs, so `expect=list` there. `data: []` under `status: 200` is
therefore a valid read that reports an empty queue; a missing `data` key raises.

## 3. Control tests, by name, and what each proves

In-suite controls (all in tests/test_outreach.py, each marked `__CONTROL` in
its docstring):

  * `test_narrowing_to_the_integer_arm_refuses_the_string_route` - narrows
    `SUCCESS_VALUES` to `(200,)` and the REAL outreach-step fixture stops
    reading. Proves the string arm is genuinely checked.
  * `test_narrowing_to_the_string_arm_refuses_the_integer_routes` (x4,
    parametrised) - narrows to `("success",)` and all four REAL 200-fixtures
    stop reading. Together with the above, this pair also rules out a
    truthiness check, which would accept both arms and a 401 as well.
  * `test_the_captured_order_is_not_already_stalest_first` - proves the ranking
    has work to do. MEASURED: the capture arrives NEWEST first, so a no-op sort
    would headline a 2-day-old reply over the 12-day-old one.
  * `test_a_shuffled_copy_comes_back_in_the_same_ranked_order` - deterministic
    shuffle (`random.Random(20260823)`), identical ranked output, and the test
    first asserts the shuffle really changed the input order.
  * `test_pending_with_its_data_key_deleted_raises` and
    `test_the_empty_and_the_missing_inputs_differ_only_in_that_one_key` - the
    empty-list queue and the missing-data read are two different inputs with
    two different outcomes, and the second test proves the two inputs differ in
    exactly one key so nothing else can be producing the difference.
  * `test_the_canned_reason_really_is_in_the_payload` - proves the canned-reason
    exclusion does real work: the string is on all 32 Completed rows and zero
    Failed ones.
  * `test_a_cross_check_can_actually_fail` - moves one counter in one captured
    payload and the read-through's agreement report breaks and lands in
    `disagreements`.
  * `test_a_swapped_pair_of_shapes_is_refused` - passes plan and dashboard in
    each other's slots and `agent_readthrough` refuses.
  * `test_a_consenting_capture_would_drop_the_line` - flips the captured
    consent value and the disagreement disappears, proving it is emitted
    because the values differ and not because it is hardcoded.
  * `test_the_leak_sweep_can_actually_fire` - the contact-route sweep, shown
    firing on a planted address.
  * `test_the_clock_scanner_fires_on_a_planted_call` - the static no-clock sweep,
    shown firing on a planted `datetime.now()` line.

Reverted-guard measurements. Each guard put back the way it would have been
written without the scar behind it, measured against the 86 tests. Harness:
`scratchpad/ctl_outreach.py` (disposable; it patches one symbol then calls
`pytest.main`). Not harvested into an instrument register - it is five
one-line reverts, not a tool.

    ctl_status   unwrap stops checking `status` (the truthiness version)  -> 17 failed
    ctl_rank     _rank_by_staleness = lambda rows: rows                   ->  7 failed
    ctl_empty    a missing `data` key reads as an empty container         ->  3 failed
    ctl_canned   _failure_reasons counts ALL rows, canned string included ->  2 failed
    ctl_slots    _require_shape stops proving a shape is in its own slot  ->  2 failed

Two guards were extracted into named module functions (`_rank_by_staleness`,
`_failure_reasons`) purely so they could be reverted and measured; the logic is
unchanged.

## 4. Honesty positions taken

  * Two disagreements are REPORTED and neither is resolved: `auto_run: 1` (step)
    against `auto_run_consent: false` (dashboard), assembled in
    `agent_readthrough` because that is the only place both payloads are in
    scope; and `consent_email_job_scan: true` (dashboard) against
    `has_consent: false` measured on `talent/outreach/interview-list`, carried
    with its receipt (`tests/fixtures/talent_interviews.json`) and emitted only
    while the two values actually differ.
  * 8 positive and 7 unseen are printed as two INDEPENDENT counters. The
    payload never says the 7 are among the 8, so the module does not either.
  * `max_limit: 8` is carried verbatim and explicitly NOT described as a daily
    quota; what Uplers caps at 8 has not been measured.
  * `all_over_status` and `conversion_offer` are carried under `unread_fields`
    and read by nothing, because their meaning is not documented anywhere this
    server can see.
  * Four cross-checks are computed and printed with their sources, so agreement
    is visible rather than assumed: jobs run (48 = 48 = 48), replies waiting
    (7 = 7 = 7), resumes tailored (0 = 0), jobs queued (0 = 0). A mismatch
    lands in `disagreements` and names every side.

## 5. What surprised me - five things, in order of weight

**(a) THE COMMITTED FIXTURE CONTAINS REAL UNREDACTED CONTACT DATA. Not mine to
fix; escalating.** `git diff tests/fixtures/outreach_missed_followups.json`
shows the working-tree file is the redacted one and the COMMITTED version is
not. The committed blob carries real full names, real business email addresses,
real linkedin.com/in profile URLs, the operator's own gmail address, real Gmail
thread ids, and the verbatim text of seven people's replies. The redaction
landed as an uncommitted modification on top of a commit that already has the
raw data, so it is in git history. I did not touch that file or git. Decide
what you want done before this repo goes anywhere.

**(b) The suite baseline in my brief was wrong, and it moved twice more while I
worked.** Brief said 983. Measured at slice start: **985 passed**. Measured at
slice end with my file ignored: **1104 passed**. Full suite with my file:
**1190 passed**, i.e. my 86 tests, zero breakage. The drift is three sibling
slices landing concurrently (`tests/test_assessment_flags.py`,
`tests/test_preference.py`, `tests/test_saved_filter.py` and their modules are
all untracked in the working tree). Nothing about it changed my design, so I
kept going rather than stopping - but the number in the brief cannot be used as
a gate any more; use "1104 without my file, 1190 with it" instead.

**(c) `discard_reason` is populated on rows that SUCCEEDED.** You warned the
canned string was canned. What the census adds: the canned "unknown reason -
contact support" string appears on EXACTLY the 32 Completed rows and on ZERO of
the 16 Failed rows. So on a Completed row it is not a weak diagnosis, it is a
placeholder on a run that was never discarded at all. `failure_reasons` is
built from Failed rows only; the canned count is reported separately as
`canned_reason_rows`.

**(d) The dead LinkedIn channel is measurable in Uplers' own failure text.**
11 of the 16 failed runs carry the reason "Public Indian employee email IDs
were not available for this company. Tip: Connect your LinkedIn account with
Happy Agent to reach employees through LinkedIn." That is 11 of 48 runs lost to
the one channel that is switched off, in the platform's own words, and it lands
in the read-through as an action line rather than an inference of mine. The
remaining five: 3 "no publicly available Indian employee data", 1 blocked
company, 1 duplicate conversation already in his inbox.

**(e) Two smaller measured quirks, both handled.** `agent-tailor-activity`
spells its booleans `"Yes"` / `"No"` with a capital letter, which
`talent_shape.truthy` answers `None` to - unhandled, all 48 rows would have
landed in `unstated`, so there is a thin `_flag()` wrapper that adds only that
spelling and delegates everything else. And `activity_date` carries NO timezone
offset while `replied_at` carries `+05:30`, so activity stamps are reported as
strings and never ordered against or subtracted from the offset-bearing ones;
`activity_stamps_carry_offset: False` says so on the face of the shape.

## 6. One judgment call for you to rule on

The missed-follow-up rows emit `contact_name` (the point of the report),
`reply_category`, `reply_summary`, `thread_subject`, `via` and
`gmail_thread_id`. They WITHHOLD every email address, `employee_linkedin_url`
and `message_full`, listed by name in `withheld_fields` so nothing is dropped
silently - `talent_shape.PRIVATE_KEYS` already bins "email" as private and a
shaped result ends up in transcripts.

`gmail_thread_id` is the borderline one. It is HIS mailbox handle rather than
another person's contact route, and it is what lets him jump straight to the
thread, so I kept it - but `scripts/capture_outreach.py` masks it in fixtures,
so there is a defensible reading in which it should not be printed either.
Your call; it is one entry in `WITHHELD_CONTACT_KEYS` either way.
