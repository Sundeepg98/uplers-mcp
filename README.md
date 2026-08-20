# uplers-mcp

A read-only MCP server for the [Uplers](https://platform.uplers.com) talent board.

It exists for one reason: **Uplers publishes the end client's name.** LinkedIn shows those same
requisitions as "Uplers" and stops there. The Uplers API names the actual company, its industry
and its website, alongside a typed pay band, a must-have/good-to-have skill split, the notice
period the client will accept, the shift window and any required assessments. That turns an
unresearchable staffing listing into something you can target.

No login, no account, no browser, no scraping of a logged-in surface. One public JSON endpoint
plus the public sitemap.

---

## Status

| | |
|---|---|
| Stack | Python 3.11+, FastMCP (`mcp`), `httpx`, stdlib `sqlite3` |
| Size | 1,811 lines of server code (1,215 excluding docstrings), 2,125 lines of tests |
| Network surface | 2 public GET endpoints, no auth |
| Maintenance estimate | 1-3 hours/month |
| Verified live | 2026-08-20 - 235 native requisitions indexed and cached |

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

## The 5 tools

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

## Deliberately out of scope

No apply, no outreach, no resume tailoring, no resume health check, no referral agent. Those
endpoints (`talent/hr/intrested`, `talent/outreach/*`, `talent/tailor/*`,
`talent/resume-health-check/*`, `talent/referral-agent/*`) are Uplers' own paid candidate
products and need the authenticated session this design avoids. Reimplementing them for free
against a marketplace whose value is a human recruiter advocating for you is a bad trade.

**This server never logs in, never mutates, and never applies to anything.**

---

## Install and run

```bash
cd D:\Sundeep\projects\job-hunting\mcp-servers\uplers
python -m venv venv
venv\Scripts\python.exe -m pip install -r requirements.txt
venv\Scripts\python.exe -m pytest        # 198 tests, no network
venv\Scripts\python.exe server.py        # stdio MCP server
```

Registered in `D:\Sundeep\projects\job-hunting\.mcp.json` as a stdio server named `uplers`.

State lives in `uplers\data\uplers.sqlite3` (gitignored, ~11 MB with the full aggregated id set).
Delete it to start clean; `uplers_sync_index()` rebuilds it. Override the location with the
`UPLERS_DATA_DIR` environment variable.

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
   `uplers_list_new_since` degrades (ids decode to `None` and drop out of date queries) but
   nothing else does. `ids.py` is the only file to touch.

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

**Failure philosophy.** A failed fetch never becomes an empty list. `uplers_search_opportunities`
raises if the index is empty rather than returning zero rows; when the index *is* populated and
nothing matches, it returns `matched: 0` with a note saying so explicitly. Batch fetches report
successes and failures side by side and `FetchReport.ok` is False if anything failed.

---

## Tests

`venv\Scripts\python.exe -m pytest` - 198 tests, all offline via `httpx.MockTransport`, against
6 real captured API responses in `tests/fixtures/` (see `tests/fixtures/MANIFEST.md` for why each
one is there). Coverage spans the native/aggregated split, the id date decoder, every filter, the
sitemap union, the market-stats maths, and the error paths. No test touches the network or the
real `data/` directory.
