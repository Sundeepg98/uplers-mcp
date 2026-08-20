# uplers-mcp

A read-only MCP server for the [Uplers](https://platform.uplers.com) talent board, plus a local
shortlist, application tracker and fit-scoring layer on top of it.

It exists for one reason: **Uplers publishes the end client's name.** LinkedIn shows those same
requisitions as "Uplers" and stops there. The Uplers API names the actual company, its industry
and its website, alongside a typed pay band, a must-have/good-to-have skill split, the notice
period the client will accept, the shift window and any required assessments. That turns an
unresearchable staffing listing into something you can target.

No login, no account, no browser, no scraping of a logged-in surface. One public JSON endpoint
plus the public sitemap.

**Nothing here ever applies to anything.** `uplers_track` records what you already did by hand.

---

## Status

| | |
|---|---|
| Stack | Python 3.11+, FastMCP (`mcp`), `httpx`, stdlib `sqlite3`, [`jobcore`](../jobcore) |
| Tools | **22** - 5 board readers, 17 profile-aware |
| Size | 5,353 lines of server code, 5,141 lines of tests |
| Tests | **444**, all offline |
| Network surface | 2 public GET endpoints, no auth |
| Maintenance estimate | 1-3 hours/month |
| Verified live | 2026-08-20 - 235 native requisitions indexed; every tool called over stdio |

---

## The one thing to understand: native vs aggregated

The board is two populations wearing the same clothes, and the difference is the whole product.

| | Native | Aggregated |
|---|---|---|
| Count (2026-08-20) | **235** | **39,372** |
| Id shape | `HR` + **12** digits | `HR` + **16** digits |
| `is_aggregator_job` | `false` | `true` |
| `job_nature` | `Uplers On-Boarded` / `Mavlers Inhouse` | `Aggregated` |
| What it is | A real Uplers requisition with a named end client | A posting scraped from elsewhere and republished |

The ~39k aggregated postings are ordinary Indian corporate jobs (Visa, Amazon, Google, Citi,
JPMorgan) that the JobSpy and Naukri servers already cover. Surfacing them here would drown the
235 records that carry the unique data.

**So every tool defaults to native-only.** `include_aggregated=True` exists, is off by default,
and every row carries an `is_native` flag. `uplers_sync_index` indexes aggregated *ids* but
deliberately does not fetch their records - and says so if you ask for them anyway.

The 12-digit native ids encode their own creation time as `DDMMYYHHMMSS`, which is what makes
`uplers_list_new_since` free. Exactly one live id (`HR0191124125506`) is 13 digits and decodes to
nothing; it is classified `unknown` from the id and `native` from its record, which is the right
answer, because **the record's own `is_aggregator_job` field is authoritative, not the id length.**

---

## The 22 tools

Five read the board. Seventeen answer "what is on it **for me**, and what have I done about it".
Everything in the second group runs against the local index and costs **no network at all**.

### `uplers_sync_index(hydrate=True, fetch_budget=300, refresh_stale=True)`
Builds and refreshes the local index. **Run this first.** Fetches `sitemap.xml`, unions every
requisition id into a persistent sqlite store, decodes native creation timestamps, then fetches
job records for native requisitions that are missing or stale. Safe to run repeatedly; each run
strictly improves coverage. First run takes about 90 seconds for ~235 records.

### `uplers_search_opportunities(...)`
Filters the local index. Native-only by default.

`skill` - `title` - `company` - `min_yoe` / `max_yoe` (bound the role's own required minimum) -
`yoe_admits` (your experience; keeps roles whose band admits you) - `mode_of_work` / `remote_only` -
`currency` - `min_pay_usd_year` - `joining_period` / `min_notice_days` - `include_aggregated` -
`sort` (`newest` | `oldest` | `pay_desc` | `pay_asc` | `least_competition`) - `limit`.

`min_notice_days` is the sharpest filter on this board: of 235 native requisitions, **121 want 15
days' notice, 75 want 30, 35 want you immediately, and only 4 accept more than 30 days.** If you
carry a 60- or 90-day notice period, that number decides whether Uplers is usable for you at all.

### `uplers_get_opportunity(hr_number, refresh=False, full_description=False)`
Full record for one requisition: end client with industry and blurb, must-have vs good-to-have
skills, the pay band in local currency *and* Uplers' USD/year normalisation, the IST shift window,
notice period, hiring model, and required assessments. Cached with a 24-hour TTL.

### `uplers_list_new_since(iso_date, limit=50, include_unhydrated=True)`
What appeared since a date. Free - native ids carry their own timestamps, so this needs no network
at all. Known-but-unfetched ids are reported in `unhydrated` rather than dropped.

### `uplers_get_market_stats(group_by="role", ...)`
Salary-negotiation intelligence, and arguably worth more than the listings. Groups the native
cohort by `role` | `skill` | `mode_of_work` | `currency` | `company` | `joining_period` |
`industry` and reports USD/year percentiles, median required experience, remote share, top skills
and currency/notice splits. Live output on 2026-08-20:

```
population 235   median required experience 4.0 yrs   remote share 0.43
USD/yr band-low  p25 19,961 | median 29,866 | p75 44,436     band-high median 36,000
currencies  INR 179 | USD 53 | AUD 2 | GBP 1
mode        Remote 101 | Office 100 | Hybrid 34
top skills  Python 89 | AWS 36 | Java 30 | TypeScript 28 | CI/CD 26 | Kubernetes 21
by skill    TypeScript med 41,918-51,420   Python med 35,415-42,024   SQL med 28,366-34,931
```

Because Uplers publishes a normalised USD/year band on most native requisitions, this is one of
the few sources of comparable pay data for India-based remote work - useful when negotiating a
role that has nothing to do with Uplers.

---

---

## The profile-aware half

### The governing constraint: token cost

Maintenance is an occasional cost. **Reading a result is a cost that recurs on every single
call, forever.** That asymmetry is why capability is pushed into the server rather than into a
browser session, and why every result here is shaped rather than dumped.

Measured on 2026-08-20 against the real 235-requisition index, as the JSON an MCP client
actually receives. **The exact call is given for each row, because these numbers are not
properties of a tool - they are properties of a tool plus its arguments plus, for the brief, the
window it covers.** An earlier version of this table quoted "1,425 chars" for `uplers_daily_brief`
with no parameters at all; it was not reproducible and it was not right.

| Call | Result size |
|---|---|
| `uplers_daily_brief(limit=3, since="2026-08-13", peek=True)` | **1,615 chars** |
| `uplers_daily_brief(limit=5, since="2026-08-13", peek=True)` | 2,325 chars |
| `uplers_rank_opportunities(limit=5)` | 1,920 chars |
| `uplers_rank_opportunities(limit=10)` | 3,414 chars |
| `uplers_assess_fit` (full reasoning for one role) | 844 chars |
| `uplers_scheduler_status()` | 210 chars |
| the longest single ranked row | 343 chars |
| one raw API record, for comparison | ~112 fields |

**The brief's size tracks its window, by design.** `since` defaults to the last brief - seven days
on a first run - so the figure moves with how many requisitions landed. On the same index on the
same day, `limit=3` ranged from **509 chars** (a one-day window with nothing new) to **1,698**
(the default seven-day window), and `limit=10` over a week reached **4,206**. A single number
without its window is not a measurement of anything.

Two of these are enforced rather than merely recorded. `tests/test_brief_size.py` pins an
**absolute ceiling** on the brief against the fixture cohort, where the window can be held fixed
and the number is reproducible in CI; the two older checks in `tests/test_tier2.py` assert only
relative bounds (a row under 600 chars, ten rows cheaper than two raw records) and are kept for
what they are.

Three rules get it there, and they are enforced by tests:

1. **Empty fields never reach the wire.** Every compact model prunes `None`, `[]`, `{}` and `""`
   on serialisation, so a row says only what it has to say. Every field therefore carries a
   default, which also keeps it out of the schema's `required` list - otherwise the pruning would
   produce output a client rejects.
2. **Composites render as one short string.** A pay band is `"$60k-90k/yr"`, not eight fields.
   A verdict is `"strong"`, not `"Strong match - apply confidently"` - derived from jobcore's own
   wording rather than re-thresholded, so a change there is followed rather than contradicted.
3. **Counts before rows, and no URLs.** "23 new, here are the 3 best" beats twenty-three rows.
   `hr_number` is the key to `uplers_get_opportunity`, so repeating a 60-character URL on every
   row of every ranking - the single largest avoidable cost in the server - simply does not happen.

### Fit scoring

Scoring is [`jobcore`](../jobcore)'s, the same engine the Naukri server uses, so **a 78 here means
what a 78 means there.** This server only translates, and is honest about the three places where
Uplers' data does not map cleanly:

| Trap | What would go wrong | What is done |
|---|---|---|
| **Units** | jobcore's Salary is denominated in lakhs. Handing it `"INR 9,00,000-15,00,000 / year"` reads 900,000 as a US salary and scores every Indian role as a windfall. | A Salary type is bound to USD/year (`lakhs_multiplier=1.0`), and **only** Uplers' own USD normalisation is passed. A local-currency band with no USD figure scores no salary bonus at all, which is correct: there is no evidence either way. |
| **Unbounded experience** | Uplers writes `max_yoe = 0` to mean "no upper bound". Taken literally, every experienced candidate is wildly over-qualified. | An unbounded ceiling is raised to the candidate's own years - which is what "no upper bound" means for them. |
| **Must-have vs good-to-have** | jobcore scores one flat skill set; Uplers types its skills. | The split is reported *alongside* the score as `must_have` coverage, never folded into it. Two servers whose scores are computed differently could not be compared, and comparability is the point. |

**Blockers are not score deductions.** A notice period the client will not accept, a company on
your avoid list, an experience floor you are years under, or **zero coverage of the client's
mandatory skills** make a role ineligible. A 92 you cannot take is more useful labelled than
quietly turned into a 71, so those are listed in `blockers` and excluded from rankings by default
(`exclude_blocked=False` shows them with their reasons).

That last blocker was found on the live cohort during the build: an Angular/.NET requisition
ranked **first** against a Node profile, scoring 90, because its two good-to-have skills (AWS,
Azure) matched while its single must-have (.NET) did not. Promoting zero must-have coverage to a
blocker moved 73 such roles out of the ranking and put genuine backend matches at the top.

### The stack preference: ranked lower, not hidden

The operator would still take a Python backend role - he has years of it and it stays on his
profile, earning him matches - but Node/TypeScript is the direction he is moving in. So a
**Python-leaning** requisition (one that wants the Python stack and does *not* want the Node one)
sorts below an otherwise-comparable Node role.

The mechanism is one signed integer, `PREFERENCE_TILT = 4` in `uplers_server/fit.py`, applied in
one place, and it is careful about three things:

- **It is not a filter.** Python roles keep their place in `ranked` and `scanned` and still appear
  with their real score. Nothing is removed.
- **It is not a score change.** `overall_score` stays exactly jobcore's, so a 78 here still means
  what a 78 means on the Naukri server. Comparability across boards is the reason jobcore exists
  and a personal stack preference is not allowed to spend it. The adjustment is reported separately
  as `rank_adjustment`, and the row carries a `python-leaning stack: ranked -4, score unchanged`
  flag so a demotion is never silent.
- **It cannot outweigh a real difference.** 4 is deliberately just under jobcore's smallest
  structural bonus (+5 each for location, remote, salary fit, agent eligibility). A stack
  preference should decide a near-tie; it should not overrule "this role is actually remote", and a
  Python role that is genuinely five points the better match still ranks first.

A role wanting **both** stacks is not demoted - that is the path he is already on - and a role
wanting neither is left alone. To retune it, change `PREFERENCE_TILT` or the two frozensets;
`tests/test_fit.py` pins the intended ordering, including the case where the tilt must lose.

### The pay floor: currency-blind, because Uplers already converted

`min_pay_usd_year` is set to **20,959**, which is ₹20,00,000/year.

That figure is **not** this server applying an exchange rate - it is Uplers' own. Requisition
`HR140826172010` in the live index reads `INR 20,00,000-25,00,000 / year` and Uplers publishes it
as `$20,959-$26,198`. Uplers normalises **every** requisition to USD/year whatever the local
currency (measured 2026-08-20: 179 INR, 53 USD, 2 AUD, 1 GBP - and all 235 carry the dollar
figure), so an INR band and a USD band are already commensurable and one USD floor compares both
correctly.

Reaching for a plausible rate instead would be the bug. At ~₹88/USD, ₹20,00,000 reads as $22,727 -
which would quietly turn a ₹20 LPA floor into a ₹21.7 LPA one and mark genuine ₹20 LPA roles as
below it.

Two honest caveats:

- **Uplers converts once, at the rate current when the requisition was posted, and never
  re-normalises.** Across the 100 INR reqs with a parseable annual band the implied rate runs from
  85.5 on mid-2025 postings to 95.4 on August-2026 ones, 59 of them at 94.9-95.4. So an old,
  slightly-underpaying role can clear a floor derived from a recent band. The error is
  one-directional and it is the safe direction - a stale role is admitted rather than a qualifying
  one hidden - and recent postings, the ones worth applying to, convert exactly.
- **Unknown pay is not pay below the floor.** 111 of the 235 native requisitions (47%) are
  confidential-budget. All of them still carry Uplers' dollar figure, so they are compared
  normally; but a requisition with *no* published figure is **admitted and flagged**
  (`no USD band published, pay unverifiable`), never dropped. `uplers_search_opportunities` treated
  a missing figure as a failing one until 2026-08-20, which meant a pay floor could silently delete
  a large slice of the board while reporting a clean result.

A role whose band tops out below the floor is flagged, not hidden, when the floor comes from your
profile; passing `min_pay_usd_year` explicitly to a search or ranking call is a filter and does
exclude.

### Profile

`data/profile.json` - deliberately a file, not a database row, so you can open it, see exactly
what your scores are computed against, and fix a wrong line in a text editor.

On first use it seeds itself from the résumé markdown in `job-hunting/resumes/` (override with
`UPLERS_RESUME`) and says so. It never invents one: no résumé and nothing set means
`uplers_get_profile` raises with an instruction, because an empty profile scores 235 requisitions
identically and the numbers would look real.

**`notice_period_days` is the field that matters most.** Of 235 native requisitions, 121 want 15
days, 75 want 30, 35 want you immediately and only 4 accept more than 30. Until it is set, no role
can be ruled out on notice, and every tool says so.

### The 17 tools

| Tool | What it is for |
|---|---|
| `uplers_get_profile` / `uplers_set_profile` | What every score is computed against. Set-only-what-you-pass; `add_skills` / `remove_skills` are incremental. |
| `uplers_assess_fit(hr_number)` | One role, full reasoning: matched and missing skills, must-have coverage, experience, bonuses, blockers, flags. |
| `uplers_rank_opportunities(...)` | **The main tool.** Scores the cohort, drops what you are blocked from, returns the best few as compact rows. Ordered by score adjusted for the stack preference, then raw score, then must-have coverage. |
| `uplers_save_job` / `uplers_list_saved` / `uplers_unsave_job` | Local shortlist. Stores a title snapshot, so it keeps reading correctly after a requisition closes; `still_listed: false` marks those. `uplers_list_saved` re-scores against the *current* profile. |
| `uplers_track` / `uplers_update_status` / `uplers_list_tracked` | Your pipeline: interested / applied_manually / responded / interviewing / rejected / closed. Every call appends to a history, including a repeat of the same status, because "still nothing on the 14th" is information. `uplers_update_status` refuses an id you never tracked, so a typo cannot invent progress. |
| `uplers_set_alert` / `uplers_list_alerts` / `uplers_delete_alert` | Stored filters, evaluated locally - no Uplers alert API, no email, zero network for twenty alerts. Each alert reports a requisition **exactly once**; re-saving a name changes the criteria and clears that memory, so a widened alert reports what it now covers. |
| `uplers_daily_brief()` | Start here. New requisitions ranked by fit, alerts that fired, shortlist entries you have not actioned, applications gone quiet, and index freshness - in ~1.4 KB. Calling it advances the window; `peek=True` looks without consuming. |
| `uplers_skill_gap()` | Not a popularity chart. `sole_blocker` counts roles where a skill is the **only** must-have you lack - the ones learning it alone would unlock - with the pay delta against the cohort median attached. |
| `uplers_company_intel(name)` | The end client: blurb, industry, website, plus every requisition they have open, their pay range, notice and mode habits, and how long they have been hiring. A fragment matching several clients returns the candidates rather than guessing. |
| `uplers_scheduler_status()` | Is the index refreshing itself, and which process is doing it. |

### Background freshness, with two MCP clients

Claude Code and Claude Desktop both register `uplers`, so **two processes run against one sqlite
file.** A naive interval task would run twice and double the traffic to a public endpoint we are a
guest on. Three guards, each insufficient alone:

- **A lease** (`leases` table, one conditional `UPDATE`) - exactly one process fetches. It
  expires, so a process killed mid-sync does not lock the other out forever. `owner` naming
  another process is the healthy case, not a fault.
- **A due check** on `last_sync` - the lease says *who may*, this says *whether anyone should*.
- **An attempt floor** - `last_sync` is stamped by the sync itself, so a sync that *fails* leaves
  it old and the due check keeps saying yes. Without a separate floor, a broken endpoint would be
  retried on every 15-minute poll forever. Stamped before the attempt, so it holds even if the
  process dies mid-sync.

The task starts on the first tool call, not at import, so nothing spawns a background task by
merely importing the module. It catches everything and records it rather than raising into the
event loop. Turn it off entirely with `UPLERS_AUTO_SYNC=0`.

sqlite runs in **WAL** mode with a 10s busy timeout for the same reason: two processes, one file.

### Migrations

The store already holds data - an ~11 MB id set built over real sync runs - so the schema cannot
just be redefined. Changes ship as numbered migrations in `migrations.py`, recorded in
`meta.schema_version`, forward-only and idempotent. A database with no version row is version 0
and is detected by that absence, not guessed. The test that matters builds a pre-migration
database by hand and upgrades it, asserting nothing that was there before is touched.

## Deliberately out of scope

No apply, no outreach, no resume tailoring, no resume health check, no referral agent. Those
endpoints (`talent/hr/intrested`, `talent/outreach/*`, `talent/tailor/*`,
`talent/resume-health-check/*`, `talent/referral-agent/*`) are Uplers' own paid candidate
products and need the authenticated session this design avoids. Reimplementing them for free
against a marketplace whose value is a human recruiter advocating for you is a bad trade.

**This server never logs in, never mutates Uplers, and never applies to anything.**

The tracking tools do not weaken that. `uplers_track(status="applied_manually")` is a note to
yourself that you went to their site and applied; it sends nothing, and the only thing it mutates
is the local sqlite file. The status is named `applied_manually` precisely so the record cannot be
misread later as something this server did.

---

## Install and run

```bash
cd D:\Sundeep\projects\job-hunting\mcp-servers\uplers
python -m venv venv
venv\Scripts\python.exe -m pip install -r requirements.txt
venv\Scripts\python.exe -m pip install -e ../jobcore   # the shared scoring engine
venv\Scripts\python.exe -m pytest        # 444 tests, no network
venv\Scripts\python.exe server.py        # stdio MCP server
```

`ModuleNotFoundError: jobcore` means the second line was skipped. jobcore is a sibling package,
not on PyPI, and it is shared with the Naukri server - **editing it changes what a live job
server scores**, so run both suites after any change there.

Registered in `D:\Sundeep\projects\job-hunting\.mcp.json` as a stdio server named `uplers`.

State lives in `uplers\data\` (gitignored): `uplers.sqlite3` (~11 MB with the full aggregated id
set, plus your shortlist, pipeline and alerts) and `profile.json`. Delete the database to start
clean; `uplers_sync_index()` rebuilds the index, but **your shortlist and application history are
in there too** and are not recoverable from Uplers. Override the location with `UPLERS_DATA_DIR`.

| Environment variable | Default | What it does |
|---|---|---|
| `UPLERS_DATA_DIR` | `uplers/data` | Where the database and profile live |
| `UPLERS_RESUME` | `job-hunting/resumes/Sundeep_Resume.md` | Resume to seed the profile from |
| `UPLERS_AUTO_SYNC` | `1` | `0` disables the background sync entirely |

---

## Maintenance notes

**Politeness.** Concurrency is capped at 4 with a 0.4s delay between requests, which measures
around 3-4 requests/second against an advertised `X-RateLimit-Limit: 500`. The client reads
`X-RateLimit-Remaining` off every response, slows to one request per 3 seconds below 100, and
aborts loudly below 20. A full sync of the native cohort costs ~235 requests.

**The sitemap is not an index - it is a sampler.** Three consecutive fetches on 2026-08-20
returned **33,160 / 39,608 / 10,811** entries, and one contained already-closed (`Won`/`Lost`)
requisitions. This is why the id store unions across fetches and never deletes on absence, and
why `last_seen` is recorded per id. Do not "optimise" this into a replace-on-sync.

**What breaks if Uplers rebuilds their frontend.** Ranked by likelihood:

1. *Nothing breaks but the data goes stale* - if `sitemap.xml` stops listing requisitions,
   discovery of new ids stops. Everything already indexed keeps working. Symptom:
   `sitemap_entries` collapses while `total_known_ids` holds.
2. *`/api/single-hr-public` is removed or gated.* This is the single point of failure. Symptom:
   `UplersError` naming an HTTP status on every fetch. There is no fallback; the endpoint is
   currently `Allow`ed in `robots.txt` and serves `Access-Control-Allow-Origin: *`, so it is
   intentionally public, but that is a decision they can reverse.
3. *Field renames.* `shaping.py` reads ~30 named fields off a 112-field record. A rename
   surfaces as `None` in a typed field, not a crash. The fixtures under `tests/fixtures/` are
   the reference shape; re-capture them and re-run the suite to find what moved.
4. *Id format change.* If native ids stop being 12 digits or stop encoding `DDMMYYHHMMSS`,
   `uplers_list_new_since` and the "new since" section of `uplers_daily_brief` degrade (ids decode
   to `None` and drop out of date queries) but nothing else does. `ids.py` is the only file to
   touch. This already happens for exactly one live id, and is tested.
5. *jobcore changes underneath you.* Fit scores are not computed here. A change to the shared
   taxonomy or the 60/40 weighting moves every score on this board **and** on Naukri; jobcore's
   golden-parity suite is what catches it.

**Quirks already handled, so do not "fix" them:**

- `YearOfExp`, `max_yoe`, `hr_yoe` and `cost` are decimal *strings* (`"5.00"`).
- `max_yoe == "0.00"` means *no upper bound*, not zero years.
- `cost_start_in_dollar` is **monthly**; `cost_start_in_dollar_yearly` is **yearly**.
- `cost_string` grammar varies: `"INR 9,00,000-15,00,000 / year"`, `"Upto INR 30,00,000 / year"`
  (a ceiling, so `local_min` is None), `"Upto GBP 549 / month"` (monthly - see `local_period`),
  and `"Confidential"`.
- `CompanyName` at the top level is the end client; `company.company_name` is usually an
  anonymised descriptor.
- `is_partner_company` is a date *string* (`"Jun 2026"`) despite the name, occasionally `false`.
- `JobDescription` and `company.about` are HTML, and some records contain U+FFFD where Uplers'
  own pipeline mangled a smart quote.
- `IsConfidentialBudget` can be true on a record that *also* carries a USD normalisation. Both
  are shown - `"confidential (est. $26-30k/yr)"` - because the estimate is what the salary bonus
  is scored on, and a figure that drives a score has to be visible next to it.

**Failure philosophy.** A failed fetch never becomes an empty list. `uplers_search_opportunities`
raises if the index is empty rather than returning zero rows; when the index *is* populated and
nothing matches, it returns `matched: 0` with a note saying so explicitly. Batch fetches report
successes and failures side by side and `FetchReport.ok` is False if anything failed.

---

## Tests

`venv\Scripts\python.exe -m pytest` - **444 tests**, all offline via `httpx.MockTransport`,
against 6 real captured API responses in `tests/fixtures/` (see `tests/fixtures/MANIFEST.md` for
why each one is there). Coverage spans the native/aggregated split, the id date decoder, every
filter, the sitemap union, the market-stats maths, the scoring adapter, migrations from a
hand-built pre-migration database, the lease under two connections, and the error paths.

Four invariants hold in every test, three of them autouse so they cannot be forgotten:

- **No network.** Every HTTP interaction goes through `httpx.MockTransport`.
- **No real data dir.** Every `Store` is built on `tmp_path` or `:memory:`.
- **No real profile.** `profile.json` is redirected to `tmp_path` and the resume seed source is
  unset, so a test can neither read nor overwrite the operator's real profile.
- **No background sync.** `UPLERS_AUTO_SYNC=0` for the whole suite, so a tool call cannot spawn
  the scheduler and reach the network behind the mock transport's back.

Seven of these tests were written because the behaviour they assert was **wrong when first
measured**, which is the only reason to trust the rest when they are green:

| Test | The bug it caught |
|---|---|
| `test_zero_must_have_coverage_is_a_blocker_not_a_flag` | An Angular/.NET role ranked first against a Node profile, scoring 90 on good-to-haves alone. |
| `test_records_with_no_usd_figures_are_ADMITTED_by_a_pay_floor` | A pay floor treated "pay unknown" as "pay too low" and dropped the role. 47% of this board hides its budget, so the filter could silently delete a large slice of it. This test asserted the **opposite** until 2026-08-20. |
| `test_the_daily_brief_has_an_absolute_ceiling` | The README quoted 1,425 chars for the brief and nothing pinned it; the real figure was 1,698 on the default window and moved with the window. Only relative bounds were enforced. |
| `test_peek_does_not_consume_alert_hits` | `peek=True` still wrote the alert seen-list, so peeking silently ate the news it was previewing. |
| `test_a_broken_alert_does_not_kill_the_brief` | Criteria were validated on write but not on read; a stored bad key was silently dropped, leaving zero filters and matching the entire board. |
| `test_a_persistently_failing_sync_is_not_retried_every_poll` | A failing sync left `last_sync` old, so the due check said yes on every 15-minute poll, forever. |
| `test_unfetched_native_ids_are_surfaced` | The unhydrated count was a subtraction of two counts that could understate or go negative. |
