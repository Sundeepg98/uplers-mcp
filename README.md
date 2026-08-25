# uplers-mcp

A read-only MCP server for the [Uplers](https://platform.uplers.com) talent board, plus a local
shortlist, application tracker and fit-scoring layer on top of it.

It exists for one reason: **Uplers publishes the end client's name.** LinkedIn shows those same
requisitions as "Uplers" and stops there. The Uplers API names the actual company, its industry
and its website, alongside a typed pay band, a must-have/good-to-have skill split, the notice
period the client will accept, the shift window and any required assessments. That turns an
unresearchable staffing listing into something you can target.

There are two tiers, and the line between them is the first thing to read.

**The public tier** - 24 tools - needs no login, no account and no browser. One public JSON
endpoint plus the public sitemap. It never applies to anything and never mutates Uplers:
`uplers_track` records what you already did by hand.

**The authenticated tier** - 38 tools, first added 2026-08-21 - reads *his account*, and the
difference is the whole reason it exists: the public board shows what Uplers is hiring for, his
account shows what Uplers is doing about **him** - which requisitions he has been matched to, what
their recruiters have moved to interview, and what his profile looks like to the people making
that call. Of the thirty-eight: four manage the session, twelve read his account, four read the
output of the paid outreach agent he already owns, two read the paid candidate products he has
already bought, one syncs his Uplers profile down into the local one, two list local restore
points, two write to a requisition, four write to his PROFILE, five configure that paid agent, and
two withdraw a permission or publish something that cannot be taken back. Those thirteen writes
are four different kinds of act: `uplers_apply` **cannot be undone** and `uplers_dismiss` can;
`uplers_replace_resume` is a one-way door on *Uplers'* side that only this server's local
pre-flight snapshot can reverse; the five agent-config writes are reversible by construction -
each reads its prior value before it writes and re-reads after; and the fourth kind exists
*because* that third sentence is a claim rather than a grouping - `uplers_revoke_email_scan`
withdraws a standing permission rather than flipping a setting, and
`uplers_submit_interview_feedback` is genuinely one-way, with no edit route and no delete route
anywhere in Uplers' product. See "Applying cannot be undone" before using any of them.

### This repository is published to be READ, not run

It is **proprietary**, and `LICENSE` says so explicitly rather than leaving it to
the default that silence implies: all rights reserved, provided for reference, no
permission to use, copy, modify or distribute.

That is not boilerplate, and the reason is the paragraph directly above.
`uplers_apply` expresses interest, which on Uplers **is** applying, and there is
no withdraw, no cancel and no un-apply anywhere in their product - verified as a
complete negative search over their entire frontend bundle. Somebody who clones
this and points it at their own account can do something to their own job search
that nobody can reverse. The server also drives an authenticated session against
a platform whose terms prohibit automated access.

So the code is here to be read - the API archaeology, the write guards, the
evidence trail in `_audit/` - and not to be pointed at anybody's account. If you
want to do something with it, ask.

---

## Status

| | |
|---|---|
| Stack | Python 3.11+, FastMCP (`mcp`), `httpx`, stdlib `sqlite3`, [`jobcore`](../jobcore) |
| Tools | **62** - 24 public (5 board readers, 18 profile-aware, 1 introspection) + 38 authenticated |
| Size | 19,461 lines of server code, 23,278 lines of tests |
| Tests | **1,424**, all offline |
| Network surface | 2 public GET endpoints needing no auth; 34 `talent/*` routes named as constants - 30 of them reached by a tool, four recorded and deliberately uncalled - plus `v2/assessments`, all behind a bearer token. 33 of the 34 live in `endpoints.py`; `talent/talent-download-resume-profile` lives in `resume_write.py` and says why in its own comment |
| Browser | Playwright, in exactly one module, for login only. The public tier needs none. |
| Maintenance estimate | 1-3 hours/month |
| Verified live | 2026-08-24 - the Gmail job scan read on its authoritative route (consent granted 2026-08-12, last run 2026-08-23) and 79 scanned jobs fetched; 14 agent-surface GETs captured as fixtures; 2 of them measured 404 and recorded as such. The five agent-config writes are built and tested against captured shapes, and **none of them has been fired live** - nothing in `outreach_write.py` was derived from a live probe, and no write it can send has reached his account. |

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

## The public tier: 24 tools

Five read the board. Eighteen answer "what is on it **for me**, and what have I done about it".
Everything in the second group runs against the local index and costs **no network at all**. The
twenty-fourth is `uplers_server_info`, which describes the server itself - what it can do, what it
deliberately cannot, and which commit it is running - and reaches for nothing at all to do it.
None of the twenty-four needs an account; the thirty-eight that do are documented under "The
authenticated tier" below.

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

### Configuration: one shared file, and what it may not reach

Every number that decides a score, a blocker or an order used to be a literal in a source file:
the skill/experience split, the bonus table, the verdict bands, the must-have warning ratio, the
one-year experience slack, the stack preference below. They are values now, in a shared
`jobhunt.json` that this server, Naukri and Instahyre all read. `uplers_config()` shows the file in
force, and the loader reports **every path it tried** when it finds none - because "I edited it and
nothing happened" is usually "you edited a different one".

Three properties hold it together, and each is a test rather than an intention:

- **Defaults are the old literals, exactly.** A clone with no config file anywhere scores
  byte-for-byte as this server did before any of it existed. Nothing moves until he edits.
- **The scoring path never reads a file.** `uplers_server/policy.py` does the I/O, once, at tool
  entry; `fit.py` takes the resulting binding and does none. A snapshot is immutable for the whole
  call, so a change landing mid-call cannot score half a ranking under old weights and half under
  new. An AST scan over every production module fails the build if a scoring call site is reached
  without a binding, because "use the shipped defaults" is exactly how a call site would silently
  ignore his file and still return a plausible number.
- **Some keys are not loadable at any tier.** The autonomous-apply switches on the Naukri server,
  chiefly. A file that sets one is refused **loudly** - the refusal is data in
  `uplers_config().refused` - and the Python value is used. It is never quietly dropped. This
  server has no apply-authority switch of its own to refuse; what it enforces is that nothing it
  writes can create one elsewhere: `uplers_config(write_candidate=True)` passes
  `allowed_sections=("candidate",)`, so `scoring`, a sibling server's block and even
  `servers.uplers` are all refused by name.

`candidate` is layered over `data/profile.json` field by field, and **provenance decides, not
emptiness**: `candidate.notice_period_days` defaults to `0` and `0` is also a real answer, so a
value-based rule would silently overwrite a local `30` with the shared default. A field that is
actually present in the file wins; everything else stays local, and `uplers_get_profile()` reports
which is which.

The shared `candidate` block is **not** his Uplers profile. That one lives on Uplers, he owns it,
and `uplers_sync_profile_from_uplers` is the only bridge - confirm-gated, and one-directional.

### The stack preference: ranked lower, not hidden

The operator would still take a Python backend role - he has years of it and it stays on his
profile, earning him matches - but Node/TypeScript is the direction he is moving in. So a
**Python-leaning** requisition (one that wants the Python stack and does *not* want the Node one)
sorts below an otherwise-comparable Node role.

The mechanism is a **rule in the shared config file**, `scoring.rank_adjustments`, whose shipped
default is exactly what a hardcoded `PREFERENCE_TILT = 4` and two frozensets in
`uplers_server/fit.py` used to do:

```jsonc
"scoring": {
  "rank_adjustments": [
    { "when_skills_include": ["python", "django", "flask", "fastapi"],
      "and_not": ["javascript", "typescript", "node.js", "express", "nestjs", "next.js"],
      "delta": -4,
      "label": "python-leaning stack" }
  ]
}
```

It moved because the preference is *his*, and it was compiled into a server he does not edit.
An explicit `[]` turns it off; omitting the key keeps the shipped rule. It is careful about three
things:

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
  Python role that is genuinely five points the better match still ranks first. That bound is now
  enforced in jobcore's Python rather than by the constant happening to be small: each rule's
  `delta` **and the sum of every matching rule** are clamped to ±4, and the clamp is not reachable
  from the config file.

A role wanting **both** stacks is not demoted - that is the path he is already on - and a role
wanting neither is left alone. The `and_not` clause is what makes that expressible, and it is why
this is a rule rather than a per-skill weight.

**Why not `scoring.skills.weights`?** Because the arithmetic runs backwards for the case that
matters. Weighted coverage is `sum(w[matched]) / sum(w[job])`, which *cancels* whenever the matched
set equals the job set - a pure-Python role against a profile holding Python is untouched - and
*raises* the score of a job asking for a down-weighted skill he lacks. Measured: `{node.js, django}`
scores 50 flat and 58.8 with `django` at 0.7, so down-weighting Django makes Django roles look
better. Folding the preference into the score would also convert a visible, separately-reported
ranking signal into an invisible component of a number that is supposed to mean the same thing on
every board.

To retune it, edit the file - `uplers_config()` shows what is in force.
`tests/test_fit.py` pins the intended ordering including the case where the tilt must lose, and
`tests/test_policy_wiring.py` reproduces the same -4 from a hand-written rule with the shipped one
deleted.

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

**Two decisions, two numbers, one denomination.** In the shared config the pay keys are
`candidate.pay.usd_per_year.floor` (walk-away, flags a role) and `.expected` (the target the +5
salary bonus is scored against). They were one number doing both jobs, so an unset `expected`
falls back to the floor and today's behaviour is unchanged. The band beside it,
`candidate.pay.inr_lakhs_per_year`, belongs to the **Naukri** server and is never read here.
That split is not tidiness: one shared scalar scores every job on this board +5 (a 24-lakh
expectation read as dollars clears a $60-90k band by a factor of 2,500) and every job on Naukri 0
(a $20,959 figure never clears a 25-lakh one) - and both failures look exactly like "no salary
data". Nothing is ever converted; an exchange rate is not a fact about him, and a score must not
depend on the day. When the two denominations imply an absurd rate, `uplers_config()` says so and
still converts nothing.

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

### The 18 tools

| Tool | What it is for |
|---|---|
| `uplers_config()` | Where the numbers come from: the shared `jobhunt.json` in force, its provenance, and - the field to read first - what it **refused**. `write_candidate=True` copies your local profile into the shared `candidate` block through jobcore's audited write path. |
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

---

## The authenticated tier

Thirty-eight tools behind a session he opens by hand. Everything above this point reads the public
catalogue; everything here reads what Uplers is doing about **him**, and thirteen of the
thirty-eight can change it - every one of those thirteen confirm-gated, every one previewing the
exact request first.

The evidence base for every route, parameter and encoding below is
[`../_audit/2026-08-21-uplers-bundle-callsites.md`](../_audit/2026-08-21-uplers-bundle-callsites.md)
- a static read of Uplers' own production bundle (`app.js` plus its 85 lazy chunks, **13.4 MB**),
cross-checked against live unauthenticated probes. Nothing here was guessed from a route name.
Claims in that document are tagged VERIFIED (quoting bundle source) or INFERRED (reading intent),
and this section says which it is relying on wherever the difference matters.

### Applying cannot be undone

**`uplers_apply` sends `talent/hr/intrested`, and on Uplers that IS applying.** Their own analytics
label the two call sites `"Single Opportunity - Apply"` and `"All opportunity - Apply"`. Once it
has gone through, the button is `disabled`, its label flips to **"Applied"**, and the hover text
reads *"You have already applied for this Opportunity."* That is a terminal state.

**There is no withdraw, no cancel and no un-apply anywhere in their product.** That is a complete
negative search over all 13.4 MB, not an impression: `"Withdraw"` 0 hits, `"Cancel Application"`
0 hits, `"unapply"` 0 hits. The lowercase `withdraw` occurs in exactly two places, both on the
account-deactivation screen, where the product lists *"Any of your job applications will be
withdrawn"* as a **side effect of deactivating the whole account**. A product that framed it that
way would not also ship a per-application withdraw.

So: **the only thing that retracts an application on Uplers is deactivating the account.** Treat
every apply as final.

Three things follow, and all three are built:

- **Nothing is sent unless `confirm=True`.** With `confirm=False` - the default -
  `uplers_apply` returns a preview of the exact request it *would* send (method, endpoint, body,
  `reversible: false`, and the literal call to make) and performs nothing.
- **It refuses to apply twice.** Every write first fetches the authenticated record, which costs
  one request and buys three things: proof the requisition exists, the numeric `id` the route
  actually needs, and the current state. If Uplers already has him down as interested, the tool
  says so instead of sending a duplicate.
- **It refuses to guess an id.** If the record carries no numeric `id`, it raises rather than
  substituting one of the other two identifiers. See "The identifier spaces".

`uplers_dismiss` is the opposite case and is labelled as such. Uplers ships an **explicit**
`reset_not_interested` flag for it, so dismissing a requisition is genuinely reversible and a
mistake there costs nothing. Both the preview and the result carry a `reversible` boolean, and a
performed dismissal returns the exact call that reverses it.

### Why `talent/hr/cancel-opportunity` is deliberately not exposed

Its name says "withdraw". It is not that, and shipping it as one would be the most dangerous kind
of wrong - it would imply an undo that does not exist.

Two facts settle it, both VERIFIED against the bundle:

1. **It acts on a different state.** It declines a job you have **not** applied to. Its confirm
   modal is a thumbs-down titled *"Are you sure you are not interested?"*, and its subtitle
   promises the job comes back: *"Once removed from here you can find in under 'All Work
   Opportunities"* (the unbalanced apostrophe is theirs). Meanwhile the `"applied"` branch of the
   same component renders a status label and interview links only - no cancel control at all.
2. **Its one call site is unreachable.** The button renders only when the enclosing component's
   `opportunityType === "matched"`, and `"matched"` is never passed as that prop anywhere in the
   86 files. Every literal ever passed is `"individualHrPublic"`, `"individualHr"`, `"all"` or
   `"myOpp"`; the rest is prop-drilling, which can only propagate a literal that exists. It is
   effectively dead code in the shipped build.

The route's shape is recorded in `endpoints.py` so the finding is not lost. No tool calls it.

### The login model

**Auth is a bearer token, not a cookie.** Every call site in the bundle does
`Authorization: Bearer <localStorage["token"] ?? localStorage["guest_token"]>`. **No
`X-XSRF-TOKEN` is ever attached by application code** - the only occurrences of `xsrfCookieName`
/ `xsrfHeaderName` in 13.4 MB are inside axios's own bundled default config object, and the app
sets neither, nor `withCredentials`. There is no `baseURL` and no request interceptor either;
URLs are absolute, concatenated from one constants module.

This **corrects** the earlier route-map research in
[`../../tools/uplers-api-research.md`](../../tools/uplers-api-research.md), which assumed a
`uplers_session` cookie plus an echoed `X-XSRF-TOKEN` header on mutations. That cookie does exist;
the SPA simply never relies on it. Anything built against the cookie model would have been
authenticating in a way the real client does not.

**The logged-out signal is a 401, not a 302.** MEASURED live on 2026-08-21: with
`Accept: application/json`, every `talent/*` route answers `401 {"message":"Unauthenticated."}`;
*without* that header Laravel's `Authenticate` middleware redirects to `/console/login` with an
HTML body. This client always sends the JSON header, so 401 is the normal signal - but the 302 is
still handled and `follow_redirects` is off, because following it would turn a crisp "you are
logged out" into a 200 carrying a login page, which every parser downstream would then report as a
shape change. A middleware change must not read as "logged in".

**Sessions are short-lived. Re-login is close to a daily event.** That is a property of Uplers,
not a defect here. What matters is what an expired session *looks like*: every authenticated read
reports it as **"run `uplers_login()`"** and **never** as an empty result. An empty list from
these tools always means "nothing matched" - a failed fetch that returns `[]` is
indistinguishable from a successful fetch that matched nothing, and this codebase has been bitten
by exactly that before.

**Login completes on a real authenticated request, never on a token appearing.** This is the
shape of the whole module and it is written in blood. Uplers hands anonymous visitors a
`guest_token`, and the SPA falls back to it, so *"a token exists"* is already true before anyone
signs in. The window therefore stays open until `check_auth` gets a response actually carrying his
profile back - an HTTP 200 alone is necessary but **not sufficient**, because an anonymous guest
token can also get a 200. `guest_token` is read for exactly one purpose: so a failure can say
"that was only a guest token" rather than "no token appeared".

The sibling Instahyre server shipped the shallow version of this: a login tool that returned
success the moment a session cookie appeared. Django issues those to anonymous visitors, so the
condition was already true while the login page was still painting. It closed the browser before
the operator could type and reported `authenticated: true` while every real call 401'd.

Which is why **`uplers_auth_status` can honestly return `false`.** It spends one real request
against a route whose logged-out behaviour was measured, rather than checking whether a file
exists on disk. It has three answers, and the third is not decoration:

| `authenticated` | meaning |
|---|---|
| `true` | a request came back carrying his profile |
| `false` | Uplers rejected the session. Run `uplers_login()`. |
| `null` | could not be determined - network, an unexpected 500, a 200 with no `talent_details`. **Not** the same as `false`, and not yet a reason to sign in again. |

Unknown does not collapse into false, because "you are logged out, go and sign in again" is a lie
that costs a browser round trip.

**The browser is only for login.** Playwright appears in exactly one module of this package -
`uplers_server/auth.py` - and never for fetching data. It opens the real login page, the operator
signs in with their own hands, the token is read out of localStorage, and from that point every
request is plain `httpx`. That is the same rule the public tier already follows, applied to the
one place a browser is unavoidable. Nothing here types a credential.

**Nothing sensitive is persisted or returned.** The bearer token lives in `data/session.json`
(inside the already-gitignored `data/`, `chmod 0600` where the OS honours it - on Windows that is
a floor, not a guarantee, and the gitignore is the real protection). It is **never logged, never
returned by any tool, and never put in an error message - not even its length or a prefix.** A
length is a small leak and buys nothing a boolean does not. What callers get is its *shape*:
present or absent, its format, and an expiry when one is knowable. `uplers_logout` deletes it and
leaves the persistent browser profile alone, so the next login usually needs no password.

### The identifier spaces

Three identifiers name the same requisition and the API is **not** consistent about which it
wants. Confusing them is the most likely silent bug against this API - the wrong one is a no-op or
a 422, not an obvious error. `endpoints.py` writes them down rather than remembering them:

| identifier | sent as | used by |
|---|---|---|
| `id` (plain numeric) | `hr_id` | `talent/hr/intrested` (**apply**), `cancel-opportunity` |
| `enc_id` (encrypted) | `hr_id` | `update-saved-hr`, `assign-assessment` |
| `HR_Number` (the public `HR...` string) | `hr_number` / `HR_Number` / `activeJob` | `single-hr`, `my-opportunities`, `job-not-interested`, `tailor-jobs`, and **everything in this server's public tier** |

Note the trap in the first two rows: **the same parameter name, `hr_id`, addresses two different
identifier spaces** depending on the route. Every tool here takes the public `HR_Number` and
resolves the others itself, so the distinction never reaches a caller - but it is why the write
path fetches the record first instead of accepting an id it was handed.

Response envelopes are inconsistent too: rows arrive at `res.hrs.data` on the paginated routes,
`res.data` on the masters and `tailor-jobs`, `res` directly on `single-hr`, and
`res.talent_details` on the profile. Success is the **string** `"success"` on some routes and the
**number** `1` on others. Never write one check for both.

### `uplers_my_feed` filters: four encodings that are easy to get wrong

`uplers_my_feed` builds the query Uplers' own jobs board builds, copied from their query builder
including the parts that look wrong until you check them:

| argument | what it actually takes | the trap |
|---|---|---|
| `experience` | a **range string**: `"4,6"` | it is not a number. Valid bands: `0,2` / `2,4` / `4,6` / `6,8` / `8,10` / `10,12` / `12,14` |
| `modes` | `Remote` / `Hybrid` / **`Onsite`** | Uplers says **Onsite**, not "Office", on this API - even though the public records say `Office`. Sent as `engagements`, a **JSON-encoded array of objects**: `[{"type":"Remote"}]`, not a plain list |
| `roles` | comma-joined **internal ids** | not names. Get them from `uplers_filter_options("role")` |
| `locations` | comma-joined **internal ids** | not names. Get them from `uplers_filter_options("location")` |

A bad `sort` or a bad mode raises with the valid set named, rather than being silently dropped
into a query that then returns the whole board. Uplers also reports the row count on a *separate*
call (`is_count=1`), so the total is fetched only when the paginator did not already carry it, and
a failure to get it is a note rather than a missing feed.

### Two profiles, and one of them is the record

This is the distinction most likely to be misread, because both tools are called "profile":

| tool | which profile | what it governs |
|---|---|---|
| `uplers_get_profile` | the **local** one, `data/profile.json` | what every fit score in this server is computed against |
| `uplers_my_profile` | his **real Uplers** profile | what recruiters see, and what Uplers' own matching runs against |

**His Uplers profile is authoritative.** He maintains it, deliberately; the local file exists only
so fit scores have a candidate to score against. It is a cache of him, not a record of him. So a
difference between the two is a defect in the **local** copy, and `uplers_sync_profile_from_uplers()`
brings it up to date.

`uplers_compare_profiles` therefore **reports differences and recommends nothing about his Uplers
profile.** What is on it is his decision, arrived at deliberately, and this server does not know
what he decided or why. It used to say *"Your Uplers profile is thinner than your local one (0
skills there vs 32 here)"* and tell him to go and add the missing skills on platform.uplers.com -
on the day he had just finished filling it in. That was wrong three times over: the direction, the
zero, and the presumption. See "The masters join" below.

The server **can** write to his Uplers profile - `uplers_update_profile()` - and the capability is
deliberate. Whether it should run is not a judgement this server is equipped to make, so the
capability exists, is guarded, and the decision to invoke it belongs to the calling client. Read
"Writing to his profile" before touching it: the route has replacement semantics.

Skills are **unioned** on sync, never replaced, and that is a measured decision rather than
caution. Scoring the 243 cached requisitions against a straight *replace* moved 73 of them and 71
moved up - but two email-infrastructure roles moved **down**, because the local profile carries
seven email skills (SMTP, deliverability, bulk email, RabbitMQ) that Uplers does not list. A
replace would delete real capability and quietly demote every email role. Under the union, 72 rows
rise and **none falls** - minimum delta +0 across all 243.

The correction is large and one-directional: **16 requisitions cross 70 upward and none crosses
down**, taking the shortlist from 31 to 47. Every score this server produced before this fix was
computed against 32 skills instead of 62, so every one of them was too low. Full measurement in
`_audit/2026-08-21-uplers-fit-delta.md`.

His headline and his years are **not** synced by default. "Software Engineer" vs "Backend Software
Engineer" is positioning; 5.2 vs 5.0 is a rounding convention. Neither side is obviously right, so
they go to `needs_your_decision` and stay there unless he names them in `also=`.

### Writing to his profile: replacement semantics, and the one way to get it wrong

`uplers_update_profile(add_skills=[...], remove_skills=[...], confirm=False)` changes the skills on
his real Uplers profile. It is the only tool here that changes **who he is** rather than acting on
a requisition, and it behaves differently from everything else for one reason:

> **`POST talent/profile-upsert {"field":"skills","value":[...]}` REPLACES the whole list. A skill
> left out of the array is DELETED. There is no skills delete route and no undo.**

That is VERIFIED against Uplers' own bundle, not assumed - five independent links, with verbatim
call sites in `_audit/2026-08-21-uplers-skills-write-shape.md`. The decisive one is their own
remove handler: deleting a skill chip in Uplers' UI fires **no network call at all**, it just
splices the local array. A removal reaches the server purely as an omission from the next
full-array POST. Corroborating evidence: skills is the only profile section with no
`delete-details` route, while all six of its siblings have one.

So the obvious-looking request is the catastrophic one. `value: [{"label": "Rust"}]` reads as
"add Rust" and deletes sixty skills. Five guards, each with a test:

| guard | why |
|---|---|
| Reads the live profile and sends the **complete** rebuilt list | rebuilding rows from names alone would flatten `years_of_experience` to zero on every row - which on a replacement route deletes that data |
| `confirm=False` returns the **exact request body**, not a summary | the caller is authorising a replacement write; the array *is* the decision |
| A snapshot is written **before** the request | ordering is the property - a snapshot taken after a half-successful write records the damage, not the way back |
| An empty resulting array is refused before anything is built | the single most destructive request this endpoint accepts |
| The write is re-read and **verified**, not trusted from a 200 | "the request succeeded" and "the list is what you wanted" are different claims |

`uplers_restore_profile(snapshot_id=None, confirm=False)` sends a snapshot back. It is itself a
replacement write, so it is exactly as destructive as the thing it undoes - anything added since
the snapshot is deleted by it. Its three input guards are inherited from the sibling Instahyre
server, where the version **without** them destroyed real data: a `snapshot_id` of
`"../not-a-snapshot"` escaped the snapshots directory, resolved to a file with no skills in it, and
the "restore" deleted all four of his. The id must match a strict pattern, the resolved path must
stay inside the snapshots directory, and the record must actually contain skills. Against a
replacement route the third matters most: restoring an empty snapshot is not a no-op, it is an
instruction to delete everything.

**Nothing auto-invokes it.** No read, no sync, no scheduled task and no reconciliation can reach
the write - two tests grep the source to keep it so, and `scheduler.py`, `sync.py`, `alerts.py`,
`brief.py` and `insight.py` are asserted not to import `profile_write` at all. It runs because a
caller decided it should, or not at all.

One residual uncertainty, stated because it has not been closed: static analysis proves what the
SPA **sends**, not what the server **does** with it. The server could in principle merge rather
than replace. Confirming that needs one live write, and the safe form is writing back the identical
list already there and re-reading - which the tool's own preview makes easy to inspect first. Until
someone runs it, treat replacement as the operating assumption, because it is the assumption whose
failure mode is safe.

### The masters join, and how 61 skills read as 0

`talent_details.skills` does **not** carry skill names. It carries a join table -
`{id, skill_id, talent_id, years_of_experience, order, enc_id}` - and the names live in a separate
top-level `masters` lookup of 176,329 rows shaped `{"value": <skill_id>, "label": "<name>"}`,
shipped in the same response. Read the rows without the join and no name-shaped key is found on
any of them, so the reader returned `[]` - which is indistinguishable from an empty profile.

Three sections join this way and they are reported separately, because they do not mean the same
thing to Uplers' matching:

| section | live count | joins to | meaning |
|---|---|---|---|
| `skills` | 61 | `masters.skills` on `skill_id` | everything on the profile |
| `primaryskills` | 56 | `masters.skills` on `skill_id` | a strict subset of `skills` - the technical half, and what their matching weighs |
| `tools` | 12 | `masters.tools` on `tool_id` | a separate master; on the live record it adds no new capability, only different spellings |

**667 tests passed over this bug** because every profile test in the suite built its own payload
and every one of them wrote a skill as `[{"name": "Node.js"}]` - a shape the live API has never
returned. The fix is `tests/fixtures/talent_profile.json`, captured from the live account by
`scripts/capture_profile_fixture.py`, so these tests now fail when the API changes rather than
when somebody's imagination does.

One trap the fixture also pins: Uplers' `preferred_modes` reads exactly like the local profile's
field of the same name but means **engagement type** ("Full time", "Contract"). The Remote/Office
answer is `preferred_method`, an integer resolving through `masters.preferredMethodMaster`.
Mapping one onto the other would write "Full time" into a work-mode field and silently corrupt
every mode filter downstream.

**Nothing private is modelled.** `current_ctc`, `expected_ctc`, `monthly_salary`, `dob`,
`contact_number`, `whatsapp_optin`, `address`, `email`, `profile_pic_url` and `resume_url` all
arrive in the same payload and none has a field on `TalentProfileResult`. They are stripped at
capture time and their absence is asserted, in both the committed fixture and the shaped output,
because a shaped profile ends up in transcripts, logs and reports. The private key names are
filtered out of `sections_present` too - "expected_ctc is populated" is itself a disclosure.

### The 38 tools

(This heading has now drifted four times, the same way every time. It read "17" over an
18-row table when `uplers_my_assessments` landed; it read "23" over a 23-row table
on 2026-08-24, by which point six more tools had landed - the three Gmail-scan
readers and the whole resume-write trio - and none of them had a row; it read
"29" over a 29-row table later the same day, when the five agent-config writes
landed and heading and table went stale together; and it read "34" over a 34-row
table on 2026-08-25, when the two paid-SKU reads and the two consent-and-one-way
writes landed and did exactly the same thing again. All four were corrected by
counting, not by memory. What is pinned by
`test_importing_server_registers_exactly_the_expected_tools` is the TOTAL of 62;
this per-tier heading and the rows beneath it are prose, and prose is what goes
stale. `uplers_server_info().capabilities` carries the split as a checked number
if you want one that cannot drift.)

| Tool | What it is for |
|---|---|
| `uplers_login(wait_seconds=300)` | Opens a real browser window at Uplers' login page; you type, nothing else does. Stays open until Uplers confirms a signed-in session - not until a token appears. Returns in about a second if already signed in. |
| `uplers_auth_status()` | Are we actually signed in? Measured with one real request, so `false` is a measurement. Three-valued - see the table above. Never returns the token. |
| `uplers_session_info(verify_live=True)` | How long the session has left, and what happens when it ends. **Read `credential.expiry_is_authoritative` first: on Uplers it is always `false`.** The stored JWT's `exp` sits about six months out and that date is a ceiling the token *claims*, not a promise Uplers keeps - they revoke server-side within roughly a day. `verify_live=False` is free (no network, no browser) and returns `authenticated: null` with the reason. There is no `uplers_reauth`; `renewal.why` gives the evidence for why one is impossible here, and `renewal.session_lapses_at` - the date past which no silent renew can help and you must sign in by hand - equals the credential's own expiry *because* there is no renewal path, carrying the same ceiling warning. `renewal.mechanism` states what recovery costs (a Google sign-in you complete by hand; this server never handles a password) and `renewal.uses_browser` is **null, not false** - there is no renewal mechanism here to characterise. |
| `uplers_logout()` | Forget the stored token. Local only - nothing is signed out on Uplers' side, and the persistent browser profile is left alone. Says what was lost and names the way back. |
| `uplers_my_feed(...)` | **The main authenticated read.** His personalised feed as Uplers orders it, each row carrying what he has already done about it (applied / saved / dismissed) and the ids the write tools need. Scored by the same jobcore scorer, so the numbers compare with `uplers_rank_opportunities` and with Naukri. |
| `uplers_my_pipeline(...)` | His **actual** pipeline - the applications Uplers' recruiters are working, with their own `uplers_status` and `uplers_badge` ("Interviewed", "Slots Given", "Interview Scheduled"). Where this and `uplers_list_tracked` disagree, **this one is right**: the local tracker only holds what he told this server he did. |
| `uplers_get_opportunity_live(hr_number, compare_public=False)` | One requisition as his account sees it. `compare_public=True` returns a field-level diff against the public record - the honest way to answer "is holding a session actually worth it", including when the answer is *no extra field for this one*. |
| `uplers_tailored_jobs(hr_number=None)` | Uplers' own server-side "jobs like this" suggestions, optionally anchored to one requisition. Distinct from `uplers_my_feed`. |
| `uplers_my_profile()` | His real Uplers profile: all three skill sections resolved through the masters join, per-skill years, objective, experience/education/projects, preferred cities and work-mode preference. Carries nothing private. See "Two profiles". **Note:** the live payload has never carried `profile_completion_percentage`, so that field and the note it drives are always absent - the model keeps them because an older shape had them. |
| `uplers_compare_profiles()` | Where the LOCAL profile has fallen behind the Uplers one. Writes to neither. |
| `uplers_sync_profile_from_uplers(confirm=False, also=None)` | Copies his Uplers profile into the local one, so fit scores run against the real him. Previews by default; snapshots the local file before writing; unions skills rather than replacing them; leaves the contested headline/years alone unless named in `also`. **Never writes to Uplers.** |
| `uplers_update_profile(add_skills, remove_skills, confirm=False)` | **Changes the skills on his real Uplers profile.** REPLACEMENT semantics - sends the complete rebuilt list, because an omitted skill is deleted. Previews the exact request body by default; snapshots first; verifies by re-reading. Read "Writing to his profile" first. |
| `uplers_restore_profile(snapshot_id=None, confirm=False)` | Sends a snapshot back. Itself a replacement write, so anything added since the snapshot is deleted by it. Previews by default; refuses a traversing id or an empty snapshot. |
| `uplers_list_profile_snapshots()` | Restore points, newest first. Reads disk only; needs no session. |
| `uplers_replace_resume(file_path, confirm=False)` | **Replaces the resume Uplers recruiters see, and Uplers keeps no previous copy of the old one.** No history, no versions, no revert route on their side - verified as absences across their whole bundle - and their download route takes no "which resume" parameter, so it always returns the current file. The pre-flight snapshot this takes to local disk is therefore not a safety margin on top of a recoverable act, it **is** the only rollback in existence, which is why the write refuses to send at all when the snapshot cannot be taken. Previews by default. |
| `uplers_restore_resume(snapshot_id=None, confirm=False)` | Puts a snapshotted resume back. It restores the **file**, not the record: the undo is a fresh upload, so server-side identity is new, and whether Uplers re-parses, re-scores, notifies a recruiter or touches an already-submitted application is unresolved - the preview prints that verbatim rather than summarising it. Previews by default. |
| `uplers_list_resume_snapshots()` | Resume restore points, newest first. Reads disk only; needs no session. |
| `uplers_my_interviews(detailed=True)` | Interviews Uplers has arranged for him. Read-only. See the namespace note below. |
| `uplers_my_assessments()` | Assessments HE has sat, and Uplers' own `cleared` count. The other half of a story the server previously told only from the requisition's side: 99 of the 250 indexed records demand an assessment, but nothing reported which ones he had already done. Read-only, no arguments. |
| `uplers_agent_readthrough()` | **What Uplers' own paid agent has done for him, and what it missed.** He is paying for their autonomous applier (plan 2, `outreach_mode: "auto"`) and until now none of its output was visible here. Reads six GETs and assembles them: unanswered positive replies ranked oldest-first, which of the agent's two channels is actually connected, 48 runs broken down by outcome, and a `disagreements` block where two Uplers routes report different numbers. The sixth route is the only one on this surface that counts the replies which said **no**, so `total_answered` is 10 where every other counter here stops at the 8 positives. Read-only; no write path exists in the tool or the module behind it. |
| `uplers_email_scan()` | Whether Uplers is scanning his Gmail for jobs, and what that scan found. Reads the **authoritative** consent route rather than the copy carried on the outreach dashboard, and neither of those is the `has_consent` on the interview list - that is a third consent entirely, for an interview scan whose UI Uplers designed but never shipped, wearing the identical field name. Read-only. |
| `uplers_scanned_jobs(best_for_you=None, limit=25)` | The jobs that Gmail scan actually found, listed. `best_for_you` is Uplers' own narrowing: measured 2026-08-23 as 79 rows unset and 51 with it. The route accepts no working `limit` of its own - a `limit=3` on its sibling returned all 97 rows - so any truncation here is this server's and is reported as this server's. |
| `uplers_agent_settings()` | The four switches that decide what his paid agent actually does: whether an unanswered reply gets chased, per channel, where the `disabled_followup_*` flags are **inverted** and `false` means the channel is ON; the auto-reply switch and the eight categories it would answer; the real 16-row blocklist, which is *not* the alphabetical company picker a similarly-named route returns; and whether message templates exist. Reports that a template exists and what its subject is, never the body - that body is a multi-paragraph self-description carrying employer history and a notice period. Four GETs; the write half of the same four switches is the five agent-config tools further down this table. |
| `uplers_resume_health()` | His resume health check: the score, the verdict, the attempts, and the history. Uplers splits this across two routes - one for the CURRENT state, one for the HISTORY - and this reads both, because they answer the same question from opposite sides. **It is also what makes one number readable.** The current route sends two bare counters, `user_attempts` and `total_attempts`, and nothing on it says which is spent and which is the cap; the history route independently reports its own count and returns its own rows, and all three read 3, so `user_attempts` is identifiable as the spent one by corroboration rather than by its name. That cross-check ships in the result, and if the routes ever stop agreeing the report says so instead of picking one. MEASURED 2026-08-25: he scored **89**, has run 3 checks of 5, and `is_eligible` reads `false` anyway - printed side by side and deliberately **not** reconciled, because 5 minus 3 leaves 2 and this server does not know which governs. `final_verdict` is present on every row and is the empty string on all four, so "Uplers shipped no verdict" stays distinct from "this server could not read one". The `report_details` body is withheld on purpose - it carries his name, states his city and quotes whole resume bullets back - and so are filenames and every link to the document, which is treated as a bearer credential; what that costs is listed in the result under `unsurfaced`. Read-only, two requests. |
| `uplers_tailored_resumes()` | Tailored resumes that already exist, plus the state of his tailor plan. **Not `uplers_tailored_jobs`**, which is a different surface with a confusingly similar name: that one asks Uplers which *requisitions* suit him, this one reads what the paid resume tailor has actually produced. **The trap on this route is its row count**, which is why the tool is worth having over the raw payload: MEASURED 2026-08-25, `total_records` reads 1 while `total_tailored_resumes` reads 0, because the single row is a *source* row - a base resume registered as tailoring input, with `tailored_resume: null`. Anything treating the row count as the tailored count would report a tailored resume that does not exist. The two counts are kept apart by name and each row is classified from its own fields, so the answer today is that **none** exists, from two independent readings of one payload. The plan is inactive by three fields agreeing - `plan_active` 0, `remaining_days` 0, `plan_end_date` 2026-08-11 - and that date is passed through and never compared to today, because this server's shapers have no clock. `plan_type` reads 4 and `status` reads 2; both are unlabelled integers and no meaning is attached to either, and `plan_type` is **not** an index into `talent/outreach/agent-plans`, which catalogues only ids 1 and 3. Filenames are withheld on the same rule as `uplers_resume_health`. Read-only, one request. |
| `uplers_platform_saved_jobs(search=None, ...)` | Jobs he bookmarked on **Uplers' own site**, which is a different list from `uplers_save_job`'s local shortlist and always has been. Takes `search` and nothing else: Uplers' code drops every other filter when the saved flag is set, so a filtered request would return his saved jobs *unfiltered while looking filtered*. This refuses instead of sending it. |
| `uplers_my_preferences()` | What **Uplers** thinks he wants, as opposed to what the local profile says. Fit scores here are computed against the local profile; Uplers ranks him against these, and the two had never been compared because one was invisible. Ids are resolved to labels against the lookup tables shipped in the same response; an id with no matching row is marked `UNRESOLVED` rather than dropped or guessed. |
| `uplers_assessment_gates(page_size=50)` | Which feed rows demand an assessment **before** he can apply. No new endpoint - `ai_needed` and `custom_screening_needed` already rode on rows this server reads. **Pre-apply signal only:** all 9 of his existing applications read `ai_needed: false`, so nothing here explains why they stall. Absent is reported as `unknown` and never folded into `false`. |
| `uplers_filter_options(kind, search=None)` | Turns "React" or "Bangalore" into the internal ids `uplers_my_feed` needs. `kind` is `role` / `skill` / `location` / `company`. |
| `uplers_apply(hr_number, confirm=False)` | **Applies. Cannot be undone.** Previews by default; sends nothing without `confirm=True`; refuses to apply twice. Read "Applying cannot be undone" first. |
| `uplers_dismiss(hr_number, confirm=False, undo=False)` | Mark "not interested", or reverse that with `undo=True`. Genuinely reversible - Uplers ships the reset flag. Previews by default. |
| `uplers_set_followup(gmail_enabled, linkedin_enabled, gmail_interval_days, linkedin_interval_days, gmail_message, linkedin_message, confirm=False)` | Whether an unanswered reply gets chased, per channel, and how often. **Omitted arguments are left alone.** Uplers' route takes the whole 9-key record every time, so the tool reads the live record first and carries over every field you did not name; a call that names nothing **refuses** rather than re-sending the record unchanged. Arguments read in natural polarity - `gmail_enabled=True` means "chase on gmail" - and Uplers' inversion happens once, internally. Two of their own client-side gates are mirrored, not improved on: a follow-up message must carry both `{{outreachEmployee}}` and `{{jobTitle}}` unless that channel is disabled or its message is empty, and each interval clamps to at least 1. Previews by default. |
| `uplers_set_auto_reply(enabled, hours, categories, confirm=False)` | Whether the agent answers replies for him, after how long, and to which of the eight categories. It is currently off. Enabling with an empty category list is refused, which is Uplers' own gate; a category outside the eight this account has seen is **named in the preview rather than rejected**, because Uplers may know more categories than the fixture does. `hours` gets **no floor at all** - the bundle coerces it through a minified function whose identity did not resolve, and a gate invented on unresolved evidence is a guess this repo does not make. Previews by default. |
| `uplers_set_template(channel, template, subject=None, confirm=False)` | Rewrites the outreach message on one channel; Uplers' own editor saves the two independently and so does this. **There is no delete-template route on Uplers**, so the snapshot taken before the send is the only way back, and a blank template body is refused rather than sent. `channel` goes on the wire as Uplers' integer - 1 LinkedIn, 2 Gmail. The existing body is never printed back, on any channel; what you pass **in** is echoed verbatim, because showing the exact body is the point of previewing. Writing the linkedin template does not connect the linkedin channel - see "Deliberately out of scope". Previews by default. |
| `uplers_block_company(company_id, confirm=False)` | Stops the agent contacting one company. This is the real blocklist - what Uplers means when a run fails with "You blocked this company for outreach" - and not the alphabetical company picker a similarly-named route returns. Blocking a company already on the list refuses rather than sending a write that would change nothing. Previews by default. |
| `uplers_unblock_company(company_id, confirm=False)` | The reverse, and a route pair Uplers ships and names in its own UI rather than a workaround assembled here. Takes the **company** id; Uplers' DELETE wants the blocklist **row** id, and this tool resolves that from the live list instead of accepting it from you. Both numbers sit on the same row, both are small integers, and sending the wrong one removes a different company with a 200 either way. Unblocking a company that is not on the list refuses. Previews by default. |
| `uplers_revoke_email_scan(confirm=False)` | Withdraws Uplers' standing permission to scan his Gmail for job-board alerts - `DELETE talent/outreach/consent-email-job-scan`. **It is narrower than it sounds, and that is measured rather than hedged.** It stops **future** scans only; Uplers' own success copy is future tense. **No route anywhere deletes already-ingested scan data** - a complete negative search, and the only three DELETE routes under `talent/outreach/*` are this consent, `settings/disabled-companies/{id}` and `external-apply-pending-jobs/{id}`. And it does **not** disconnect Gmail: that is a separate grant on `talent/account/gmail/disconnect`, which this server does not build. Reversible on Uplers' side - a POST to the same URL re-grants - but re-granting starts a **fresh** scan rather than resuming, which is a decision the same size as stopping one, so the grant arm is deliberately not built. Reads live first, snapshots, sends, re-reads. Previews by default. |
| `uplers_submit_interview_feedback(company_id, feedback, confirm=False)` | Publishes his feedback on an interview, and it is the one tool here that is **genuinely one-way**. There is no edit route and no delete route for submitted feedback anywhere in Uplers' product, so the snapshot is local only and cannot retract what Uplers received. Its membership guard is therefore stricter than the other writes': a `company_id` that is not on his live interview list is **refused rather than posted**. **MEASURED 2026-08-25: that list holds zero companies, so every call refuses today** - that is the tool working, not the tool broken. It was admitted on a narrower argument than the reversible five: a one-way write behind a preview, a confirm gate and a membership check is a smaller hazard than the same review published from a browser form with no preview at all. Previews by default. |

The five agent-config writes share one shape, and it is the read-before-write that makes them
reversible - not the mere existence of a route that undoes them. Each reads the live record first
(the three settings writes to carry over every field the caller did not name; the block/unblock
pair to resolve the blocklist row id and to refuse a call that would change nothing), writes a
snapshot to `data/outreach_snapshots/` **before** it sends, sends, and then re-reads the same GET
and reports whether the value actually landed. **A 200 is not proof a value changed** - three of
the four routes behind these five answer 200 and echo nothing useful, and the fourth answers with
the string `"success"`. Existing template and follow-up message bodies are never printed back:
text the caller passes in is echoed in the preview, text carried over from the live record renders
as a length and a sha256, and every redacted key is listed in `body_redacted_keys` so the omission
is visible rather than silent.

Rows here go through the same compact models as the public tier, so the shaping rules under "The
governing constraint: token cost" apply unchanged: empty fields never reach the wire, composites
render as one short string, and no row repeats a URL.

### Getting started with the authenticated tier

```
uplers_login()          # a browser window opens; sign in by hand
uplers_auth_status()    # confirms it, by measurement
uplers_my_feed()        # what Uplers is showing him
uplers_my_pipeline()    # what their recruiters are actually working
```

Re-run `uplers_login()` whenever `uplers_auth_status()` says `false` or a read tells you the
session expired - expect that roughly daily. The public tier needs none of this and keeps working
throughout.

### The namespace exception, and the line that replaced it

`talent/outreach/*` is where Uplers' **paid outreach-agent product** lives, and this server used to
exclude the whole prefix. Fourteen routes under it are now read and seven verb+route pairs are
written. The change worth understanding is not the arithmetic: **the line moved from the namespace
to the effect.** Excluding a prefix was one ruling covering 31 routes of very different character -
an analytics ping and the outreach send itself were on the same side of it, for the same reason,
which is to say for no reason about either of them.

`uplers_my_interviews` was the first exception, admitted because it is a plain GET of his **own**
interview schedule: reading your own calendar is using the platform normally, not reimplementing a
SKU.

The reads that followed on 2026-08-23, behind `uplers_agent_readthrough` and the agent-surface
tools, arrived on the same principle and a sharper fact. He is **already paying** for Uplers'
autonomous applier - measured, not inferred: `plan: 2`, `has_plan_expired: false`,
`plan_end_date: 2026-09-10`, `auto_run: 1`, `outreach_mode: "auto"`. It had run 48 jobs and
produced 8 positive replies, and this server could not see any of it. Reading the output of an
agent he already owns is the `interview-list` precedent, not a new one.

**What that emphatically does not license is building a second applier**, and this server does not
have one. The reason is not "apply cannot be undone" - Naukri has no withdraw either and this
family shipped an agent there. It is that a second *uncoordinated* agent applying from one account,
against a **250-requisition** board, through a single intermediary who gates every future match,
while the vendor's own agent already holds the wheel, is the wrong answer at any quality of
implementation.

**What told the write routes apart is an inventory, not a judgement.**
[`_audit/_slices/_slice-outreach-write-inventory.md`](_audit/_slices/_slice-outreach-write-inventory.md)
reads every write route under the prefix out of Uplers' own bundle and classifies each one by
whether it can be put back: **PAIRED** (an explicit inverse route exists, and is named),
**IDEMPOTENT-SETTINGS** (a GET serves the same record, so the prior value is readable *before* the
write), **ONE-WAY** (no inverse and no readable prior state) and **UNKNOWN** (could not be
established, with the reason given). Across the 32 verb+route pairs it lists under
`talent/outreach/*` that comes out at **5 PAIRED, 4 IDEMPOTENT-SETTINGS, 22 ONE-WAY and 1
UNKNOWN** - counted off the document's own summary table, which is the denominator to quote,
because the same document also inventories seven `talent/account/*` routes that are not under this
prefix at all.

**What was built is the reversible part, and reversibility here means it reads its prior state
back.** Two of the five tools are a route pair Uplers ships and names in its own UI; the other
three overwrite a settings record that a GET on the same data serves, so each one reads the live
record first, snapshots, sends, and re-reads to say whether the value landed. None of the five is
a send.

**What stays refused is refused route by route, each for its own reason** - which is the whole
point of replacing the prefix rule with an effect rule:

- **`store-employee-requests` IS the outreach send**, and Uplers' own UI copy says it cannot be
  undone. This is the SKU.
- `reveal-email` spends a credit to expose a person's address.
- `discard-job` drops a job out of the agent's queue with a feedback reason, one way.
- `auto-run-request` queues the paid agent at a job - the second-applier problem by another door.
- the **POST (grant) arm** of `consent-email-job-scan` starts a fresh mailbox scan, and
  `consent-auto-run` turns the autonomous applier itself on and off. Both are **reversible** and
  both are refused anyway, on **whose decision it is** rather than on safety - a different reason,
  recorded as a different reason. The grant arm is the half that *starts* something rather than
  stops it.
- the five commercial claim routes each alter a live paid subscription.

**Two names came off that list on 2026-08-25, and this entry is edited rather than left standing,
because a refusal that names something now built is worse than no refusal.** `interview-feedback`
and the **DELETE (revoke) arm** of `consent-email-job-scan` are now built - see
`uplers_submit_interview_feedback` and `uplers_revoke_email_scan`, censused together under
`consent_and_one_way`. **What changed the answer is different for each, and neither was a new
measurement overturning an old one.** The consent refusal already said it was refused on *whose
call it is* rather than on safety, and a refusal on that ground is answered by **giving him the
control, gated** - not by keeping it. So the revoke was built and the grant was not.
`interview-feedback` is the harder case and was admitted on a narrower argument: it is one-way and
stays one-way, so it ships with a guard the reversible five do not carry - it refuses any company
that is not on the live interview list, and that list currently holds **zero** companies, so it
refuses every call today. The judgement was that a one-way write behind a preview, a confirm gate
and a membership check is a smaller hazard than the same review published from a browser form with
no preview at all. `store-employee-requests`, `reveal-email`, `discard-job`, `auto-run-request`,
the grant arm and the five claim routes are **unmoved**.

**Nine** one-way routes still listed above have no constant in `endpoints.py`. They are recorded in
that file as prose, because a constant is an invitation to call it. That was **ten** until
2026-08-25: `interview-feedback` is the one deliberate exception and it now has a constant
precisely **because it is called**, which is argued at `EP_INTERVIEW_FEEDBACK` itself rather than
left to be noticed. `consent-email-job-scan` also has a constant,
`EP_CONSENT_EMAIL_JOB_SCAN`, written down before this ruling existed - it is what explains why
`uplers_my_interviews` can return an empty diary that is not "no interviews" - and it is now
**referenced**, by `uplers_server/consent_write.py` and by nothing else, which
`tests/test_agent_tools.py` asserts by AST across every module in the package. Until 2026-08-25
that test asserted the *opposite*, that nothing referenced it at all; it went red the moment the
route was wired, which is exactly what it was built to do, and it was narrowed in the same commit
rather than deleted. `consent-auto-run` appears in `endpoints.py` not at all, and still does not.

**The paragraph about a second applier above is untouched by all of this, and it is permanent.**
Not one of the seven writes now built in this namespace applies to anything, messages a person, or
reveals a contact - that line has not moved, and the two added on 2026-08-25 do not move it
either. "The write half opened" is not "the applier question reopened", and nothing in this
section should be read as softening that refusal by a single word.

The boundary is measured rather than asserted, in three places. `tests/test_agent_tools.py` and
`tests/test_agent_surface.py` each check every request their tools emit against an exact route
allowlist and assert nothing but GETs, each with a control proving the census records a write when
one happens. And since 2026-08-24 `tests/test_server_info.py` works the census backwards from the
registry: every name the census declares must be a registered tool, and every registered tool
taking `confirm=` must appear in some census group. That third one exists because the per-group
assertions could not fail for a write tool belonging to *no* group - it satisfies each equality by
not appearing in it - and `uplers_server_info` would then describe a server that can do something
it never mentions. It was planted-controlled before it was trusted.

One more route is excluded for a reason worth recording, because its name invites the mistake:
**`talent/recommendations` is not a job-recommendations feed.** Despite the name, its body is
`{key: "rnr", role: "<job title>"}` and its single caller in 13.4 MB is the *profile experience
editor* - it returns suggested bullet-point text for a CV entry. Building it as a jobs feed would
have produced a tool that silently returned the wrong kind of thing.

## Deliberately out of scope

**This section was wrong about half of what it named, and the correction is recorded here rather
than quietly applied.** Until 2026-08-25 it refused resume tailoring and the resume health check
outright, on the ground that they are Uplers' own **paid** candidate products. The read half is
now built - three routes behind two tools, `uplers_resume_health` and `uplers_tailored_resumes` -
and the sentence that justified refusing them does not survive being read closely.

**Two different arguments were wearing one name.** "Do not reimplement a vendor's paid product for
free, against a marketplace whose value is a human recruiter advocating for you" is a real
constraint and it still holds: this server does not tailor a resume, does not score one, and does
not build a referral agent. "Do not show him output he has **already bought**" was never the same
claim, and it is not defensible. The tailoring and the health check were run on his account, with
his money. Refusing to read the result back protected no boundary; it just withheld his own data
from him. Only the first argument survives, and it never covered the read side.

**The other half of the old reasoning was refuted by measurement rather than by argument.** This
section used to state that wrapping those routes "would produce tools that fail at runtime"
because the account holds zero tailor credits. MEASURED LIVE 2026-08-25 on his own session:
`talent/outreach/get-last-health-check`, `talent/resume-health-check/dashboard` and
`talent/tailor/list` each answered **HTTP 200 with real data** - a resume score of 89, three
history rows, and a plan record. **Zero 403s, zero 402s, no credit gate anywhere on the read
side.** The credit metering is real and it gates **buying** a tailored resume; it does not gate
reading the check he has already had. Captured by `scripts/capture_skus.py`.

**What stays refused is the ordering half, for a reason that does survive.**
`talent/tailor/order/create`, `talent/tailor/order/capture`, `talent/tailor/refund-request` and
the transform arm **spend money** or consume an attempt. That is his call to make and not a
tool's, so they stay unbuilt and stay nameless in `endpoints.py` - the same rule the one-way
outreach routes follow, because a constant is an invitation to call it. Every non-dashboard arm of
`talent/resume-health-check/*` is unmoved, the referral agent (`talent/referral-agent/*`) is
unmoved entire, and so is everything under `talent/outreach/*` that sends, spends or applies.

**And the tailor surface is still not bundled into his plan. That is measured, not assumed**,
because "it might be included" would have changed the answer and only a measurement can settle it.
`talent/outreach/agent-plans` returns a catalogue with exactly two entries - id 1 (Starter, 30
days) and id 3 (Elite, 90 days) - while his `outreach-step` reads `plan: 2`, a plan that is not in
the catalogue at all. The metering agrees from two independent directions: `outreach-step` reads
`credit_plan 0`, `credit_left 0`, `credit_added 0`, and `preview-config` separately carries
`plan.paid true`, `plan.expired false`, `plan.credit_left 0`. `talent/tailor/list` now adds a
third: `plan_active 0`, `remaining_days 0`, and a `plan_end_date` of 2026-08-11 already past. So
the tailor surface is credit-metered, he holds zero credits, and his tailor plan has lapsed -
which is exactly why the ordering routes stay unbuilt, and exactly what the read tools report. The
reads corroborate that finding from a third direction rather than contradicting it.

Also not exposed, each for a reason recorded above rather than by omission:
`talent/hr/cancel-opportunity` (see "Why `talent/hr/cancel-opportunity` is deliberately not
exposed"), the one-way write routes under `talent/outreach/*` **except `interview-feedback`, which
is now built and says so under "The namespace exception"**, and `talent/recommendations` (see "The
namespace exception"). Where a shape is recorded in `endpoints.py` the finding is not lost; no
tool calls any of them apart from the two named exceptions.

**The public tier never logs in, never mutates Uplers, and never applies to anything.** That is
still exactly true of all 24 of its tools, and `uplers_track(status="applied_manually")` does not
weaken it: it is a note to yourself that you went to their site and applied. It sends nothing, and
the only thing it mutates is the local sqlite file. The status is named `applied_manually`
precisely so the record cannot be misread later as something this server did.

What changed on 2026-08-21 is that a **second, clearly separated tier** can log in and can
mutate. That tier now holds **thirteen** writes that reach Uplers, in **four** groups - two on a
requisition, four on his profile, five on his paid agent's settings, and two that are neither a
requisition nor a reversible switch - and every one of them previews by default and does nothing
without `confirm=True`. **That fourth group exists because the third one makes a claim.** Every
tool in the agent-config five can be put back, and that sentence is the entire reason those five
were built while the rest of the namespace was not; filing `uplers_revoke_email_scan` and
`uplers_submit_interview_feedback` alongside them would not be a tidier census, it would silently
retire the only claim the census makes. The separation is the point, and it has not moved: nothing
in the public tier acquired a new power, its count is the same 24 it was, and the authenticated
tier is unreachable without a session the operator opened by hand. `uplers_server_info().writes`
enumerates all thirteen, grouped by what kind of thing they can change, and a test works that
census backwards from the tool registry so a write cannot be added without appearing in it.

### A second autonomous applier

There is not one, and there will not be one. The full argument is under "The namespace exception";
what belongs here is that the five agent-config writes added on 2026-08-24 do not bear on it at
all. Not one of them applies to anything, messages a person, or reveals a contact, and the routes
that would - `store-employee-requests`, `auto-run-request` - stay refused with no constant naming
them.

### Connecting the LinkedIn outreach channel: not refused, impossible from here

This one is a report rather than a shortfall, and it is worth the space because it is the
highest-value thing on this account and it costs him about a minute of his own browser.

**`POST talent/account/linkedin/connect` carries `{email, password}` - his actual LinkedIn
password - to Uplers' API**, followed by a second stage on `talent/account/linkedin/verify` keyed
on an `auth_type` of either `code_required` (a 2FA code) or `linkedin_app_approval` (approve it in
the LinkedIn app). VERIFIED from the rendered form in their bundle: `input#agent-onb-li-email`,
`input#agent-onb-li-password`, placeholder *"Enter your LinkedIn password"* - and their own card
prints *"We never see your password"* directly above that form, which is worth recording because
it is their copy contradicting their own form.

Three reasons refuse it, each sufficient on its own. **This server never handles a password** -
the same rule `uplers_login` already follows, which is why login opens a browser window and he
signs in himself. It would be a **third party's** credential handed to a vendor, not Uplers' own.
And his LinkedIn is a paid Premium Career account whose terms forbid sharing credentials.

**He connects it himself**, on the Happpy Agent onboarding card, on the button reading *"Enable
linkedin Outreach"*. That un-deadens a channel Uplers' own failure text names on **11 of 16**
failed agent runs.

The channel is dead at both ends and four routes agree: `outreach-step` says `linkedin_connected:
false` and `linkedin_template: false`; `get-message-templates` returns the empty string for the
linkedin template; `preview-config` carries its own `linkedin_connected: false`; and
`talent/account/status` **omits linkedin entirely** rather than reporting it false.
`uplers_set_template(channel="linkedin", ...)` will happily write that template, and writing it
connects nothing.

---

## Install and run

```bash
cd D:\Sundeep\projects\job-hunting\mcp-servers\uplers
python -m venv venv
venv\Scripts\python.exe -m pip install -r requirements.txt
venv\Scripts\python.exe -m pip install -e ../jobcore   # the shared scoring engine
venv\Scripts\python.exe -m pytest        # 1,424 tests, no network
venv\Scripts\python.exe server.py        # stdio MCP server
```

`ModuleNotFoundError: jobcore` means the second line was skipped. jobcore is a sibling package,
not on PyPI, and it is shared with the Naukri server - **editing it changes what a live job
server scores**, so run both suites after any change there.

### Playwright - for login only

```bash
venv\Scripts\python.exe -m pip install playwright
venv\Scripts\python.exe -m playwright install chromium
```

**Only `uplers_login` needs this.** Playwright is an optional dependency, deliberately not in
`requirements.txt`, and it is not needed to run the suite - which is entirely offline and never
launches a real browser. All 24 public tools work without it, and so do the other thirty-three
authenticated tools once a token exists: Playwright opens the sign-in window and does nothing
else. Without it, `uplers_login` returns `error: "browser_unavailable"` carrying that install
line, rather than failing obscurely.

Note that `requirements.txt` still opens with "No browser, no driver" - that comment describes the
*required* dependency set, which is unchanged, and Playwright's absence from it is the point.

### Checking a CLEAN install

```bash
venv\Scripts\python.exe scripts\clean_install_check.py
```

Clones the committed tree into a throwaway workspace, builds a brand new venv, runs the recipe
above from scratch, imports `server.py` and runs the suite - then deletes the workspace. Your
working tree and your venv are never touched.

Run it after touching `requirements.txt`, and before believing a green local suite. **A local venv
is a cache of a resolve that happened in the past**, and it cannot show you what a resolve today
would produce. On 2026-08-20 the sibling naukri server declared `mcp[cli]>=1.25.0` unbounded; `mcp
2.0.0` moved `mcp/server/fastmcp` to `mcp/server/mcpserver`, a clean resolve picked it up, and all
55 of naukri's test modules died at collection - *"5 deselected, 55 errors"*, zero tests run -
while every local run stayed green on a venv holding mcp 1.26.0 from before 2.0.0 shipped.

This server survives that move (`server.py` imports `MCPServer` with a fallback to the 1.x path,
and a clean install on mcp 2.0.0 gave *"443 passed, 1 skipped"* when that was measured on
2026-08-20, against the pre-authenticated-tier suite), which is exactly why its cap is `<3` and
not a copy of naukri's `<2`. `tests/test_requirements_pins.py` holds that reasoning in
place, reading `requirements.txt` as text - an assertion about the *installed* version would pass
happily in the very venv that hides the bug.

Registered in `D:\Sundeep\projects\job-hunting\.mcp.json` as a stdio server named `uplers`.

State lives in `uplers\data\` (gitignored): `uplers.sqlite3` (~11 MB with the full aggregated id
set, plus your shortlist, pipeline and alerts) and `profile.json`. Delete the database to start
clean; `uplers_sync_index()` rebuilds the index, but **your shortlist and application history are
in there too** and are not recoverable from Uplers. Override the location with `UPLERS_DATA_DIR`.

The authenticated tier adds two more entries to the same directory, both also gitignored:

| Path | What it holds | Safe to delete? |
|---|---|---|
| `data\session.json` | The bearer token, `chmod 0600` where the OS honours it. Never logged, never returned by a tool, never in an error message. | Yes - it is exactly what `uplers_logout()` removes. Costs one `uplers_login()`. |
| `data\browser_profile\` | The persistent Chrome profile Playwright signs in through. | Yes, but then the next login needs the password again rather than resuming. |

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

**What breaks the authenticated tier specifically.** Its whole evidence base is one static read of
a bundle they can rebuild at will, so this half ages faster than the public half. Ranked:

1. *The login flow changes.* Most likely, and the most visible: `uplers_login` opens the real page
   and waits, so a redesigned sign-in still works as long as the token still lands in
   `localStorage["token"]` on the `platform.uplers.com` origin. If they move it, the window times
   out rather than lying. `uplers_server/auth.py` is the only file to touch.
2. *The auth scheme changes.* If they move off `Authorization: Bearer` - to the `uplers_session`
   cookie the SPA currently ignores, say - every authenticated tool returns `auth_required` and
   `uplers_auth_status` returns `false` in a loop that no re-login fixes. That symptom is the tell:
   a login that reports success followed by a `false` status is a scheme change, not an expired
   session.
3. *Laravel stops honouring `Accept: application/json`.* Then the 401 becomes the 302, which is
   already handled - `follow_redirects` is off and a redirect to `/console/login` is read as
   `auth_required`. This should degrade rather than break, and it is the reason the 302 path was
   kept after the 401 was measured.
4. *A route moves.* Every route this tier calls is a named constant rather than an inline string,
   and all but one live in `endpoints.py`; the exception, `EP_DOWNLOAD_RESUME` in
   `resume_write.py`, records in its own comment that it belongs in `endpoints.py` and that moving
   it is a one-line follow-up. Re-extracting them means repeating the
   bundle read that produced
   [`../_audit/2026-08-21-uplers-bundle-callsites.md`](../_audit/2026-08-21-uplers-bundle-callsites.md)
   and, for the write half, `_audit/_slices/_slice-outreach-write-inventory.md`; both record the
   method, the exact body shape and the response envelope for each route, so they are the thing to
   diff against, not to rewrite from scratch.
5. *A filter encoding changes.* `experience` as a range string and `engagements` as a JSON-encoded
   array of objects are the two most likely to move, and the failure mode is quiet - a rejected
   filter that returns the unfiltered board. `_feed_params` is the one place they are built.
6. *`opportunityType === "matched"` becomes reachable.* Then `talent/hr/cancel-opportunity` stops
   being dead code, and the "no undo" finding needs re-checking before anything is built on it.
   Nothing here would break; the reasoning would need revisiting.

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

`venv\Scripts\python.exe -m pytest` - **1,424 tests**, all offline via `httpx.MockTransport`,
against **38** real captured API responses in `tests/fixtures/` (see `tests/fixtures/MANIFEST.md`
for why each one is there) - six job records, `talent_profile.json` (his own profile with the
private half removed by `scripts/capture_profile_fixture.py`), and the rest captured off his
authenticated account, twenty-two of them from the outreach agent's own
surfaces. Coverage spans the native/aggregated split, the id date decoder, every
filter, the sitemap union, the market-stats maths, the scoring adapter, migrations from a
hand-built pre-migration database, the lease under two connections, the error paths, and the
dependency pins themselves (`tests/test_requirements_pins.py`, read as text - see "Checking a
CLEAN install").

The authenticated tier accounts for the growth, across five new modules - `test_session.py`,
`test_auth.py`, `test_talent_client.py`, `test_talent_shape.py` and `test_talent_tools.py`. The
ones worth knowing about assert the refusals rather than the happy paths: that a `guest_token`
never counts as a session, that an HTTP 200 without `talent_details` is reported as **unknown**
rather than as authenticated, that a 401 becomes "run `uplers_login()`" and never an empty list,
that `uplers_apply` sends nothing without `confirm=True` and refuses a second application, and
that no code path puts the token in a return value or an error message.

Two later modules exist because a shape nobody had seen beat 667 passing tests.
`test_talent_profile_real.py` runs the shaper against the CAPTURED payload rather than an invented
one - every earlier profile test wrote a skill as `[{"name": "Node.js"}]`, which the live API has
never sent, so the masters join could return zero skills unnoticed. `test_profile_direction.py`
pins which profile is authoritative, and its last two tests grep the source to prove no path
writes to his Uplers profile; both were shown failing against an injected write before being
trusted, because a check that has never failed certifies nothing.

The write half added on 2026-08-24 is tested the same way: against captured settings shapes, never
against his account. Two of its checks are worth naming. The inversion is pinned in **both**
directions - asking for a channel to stay ON must produce `disabled_*: False` - because a missing
negation turns "keep gmail on" into a request that switches it off, and a *double* negation does
the same thing while looking correct at every individual call site. And the write census is
asserted backwards from the tool registry, so a tool that takes `confirm=` cannot exist without a
line in `uplers_server_info().writes` describing it.

Five invariants hold in every test, four of them autouse so they cannot be forgotten:

- **No network.** Every HTTP interaction goes through `httpx.MockTransport`.
- **No real data dir.** Every `Store` is built on `tmp_path` or `:memory:`.
- **No real profile.** `profile.json` is redirected to `tmp_path` and the resume seed source is
  unset, so a test can neither read nor overwrite the operator's real profile.
- **No background sync.** `UPLERS_AUTO_SYNC=0` for the whole suite, so a tool call cannot spawn
  the scheduler and reach the network behind the mock transport's back.
- **No ambient config.** `JOBHUNT_CONFIG=:none:` for the whole suite, so a shared `jobhunt.json`
  anywhere up the tree cannot change what a test asserts - a failure that would otherwise look
  like a scoring bug on whichever machine happened to have one. `:none:` is the explicit disable
  token; an *empty* value deliberately means "unset, keep searching", so `JOBHUNT_CONFIG=""`
  isolates nothing. `test_policy_wiring.py` opts back in per test by writing its own file.

The authenticated tier adds three more guards. These are autouse **within the modules that could
violate them** rather than in the shared `conftest.py`, which is why they are listed separately:
`test_talent_tools.py` redirects both `server._session_store` and `session.session_path` to
`tmp_path` (so no test can read or delete the real bearer token) and makes
`auth.login_via_browser` raise; `test_auth.py` redirects `browser_profile_path` to `tmp_path` and
drives the whole login handshake over fake browser objects. **No test in this suite ever launches
a real browser or touches the real `data/session.json`.**

Nine of these tests were written because the behaviour they assert was **wrong when first
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
| `test_capture_outreach_deletes_before_it_reports__CONTROL` | The capture gate scanned a fixture for PII, **reported, and then deleted** - so a print that raised left the leaking file on disk. It fired live: the output went through `head`, the pipe closed, `BrokenPipeError` landed mid-print on a route that had leaked, and `outreach_preview_config.json` stayed on disk holding a real presigned URL. It had fired once before for a different reason - a leaked value containing an emoji raised `UnicodeEncodeError` on a cp1252 console. Twice, two causes, one hole. The delete now owns the verdict and nothing that can raise sits between them. |
| `test_a_presigned_url_under_an_unenumerated_key_is_masked__CONTROL` | `resumePath.url` on `preview-config` - a 466-character presigned S3 URL, which is a **bearer credential** that downloads his resume until it expires - was caught by no DROP entry: that list is exact snake_case key names and this one is camelCase with the URL nested a level down. It escaped only because the same fixture leaked something else and was condemned for the other reason. Appending the literal key would have left the next camelCase variant just as exposed, so the load-bearing half of the fix is **value-shaped**: any presigned object-storage URL is redacted whatever key holds it. Known cost, stated at the source - an S3-hosted company logo gets masked too. |
