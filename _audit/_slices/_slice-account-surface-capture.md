# Slice: account-surface capture

Captured 2026-08-24, against a live authenticated session, GET only.

Script: `scripts/capture_account_surface.py` (new, sibling of
`capture_agent_surface.py`). Method pinned to GET in code, path pinned to an
`ALLOWED` set built from the capture tuples, asserted before `TalentClient` is
constructed. No `mcp__uplers__*` tool was called and `server.py` was not run.

**Request count: 9 GETs per full run.** The script ran three times (see
"A defect found in the leak gate", below) plus one 1-GET shape probe, so
**28 GETs total** reached the account. Nothing else was sent. The account was
not modified.

---

## 1. Headline: the LinkedIn connection

**`talent/account/status` does NOT say `linkedin: false`. It omits LinkedIn
entirely.** The whole `data` object is:

```json
{
  "data": {
    "gmail": {
      "enc_id": "XcHsnbHANBoLHDZMDbcOyXezCzBWLh45",
      "id": 4596,
      "provider": 2,
      "status": 2
    }
  },
  "jobs": [],
  "status": "success"
}
```

- **`gmail`** is present, an object, `"status": 2`, `"provider": 2`, `"id": 4596`.
  The raw response also carried `data.gmail.email`, which the `DROP` list
  removed before the fixture was written.
- **`linkedin`** is **absent**. There is no `linkedin` key at any depth. This is
  not a redaction artifact: `DROP` contains `linkedin_id`, not `linkedin`, and
  the key-path inventory is taken off the RAW body before redaction. The route
  returned 9 distinct key paths and none of them is `linkedin`.

The browser-parity census (row 39 / G10) predicted
`res.data.data.{gmail, linkedin}`. **The `linkedin` half of that prediction is
wrong** - or, more likely, the SPA renders a disconnected LinkedIn from the
absence of the key rather than from a false value.

### It AGREES with `outreach-step`, and a third route makes it unanimous

The question this capture was run to settle was whether a second reading
corroborates `outreach-step`'s `linkedin_connected: false`. It does, by
omission. A third, previously unmeasured reading settles it explicitly -
`talent/outreach/preview-config` carries its own pair, measured directly:

| reading | source | value |
|---|---|---|
| `step1.gmail_connected` | `outreach-step` (prior) | `true` |
| `step1.linkedin_connected` | `outreach-step` (prior) | `false` |
| `data.gmail` | `account/status` (this slice) | present, `status: 2` |
| `data.linkedin` | `account/status` (this slice) | **key absent** |
| `data.gmail_connected` | `preview-config` (this slice) | `True` |
| `data.linkedin_connected` | `preview-config` (this slice) | `False` |
| `data.linkedin_template` | `preview-config` (this slice) | `None` |

**Three independent routes agree: Gmail is connected, LinkedIn is not.** The
`linkedin_connected: false` finding in `_audit/2026-08-23-build-uplers.md` is
CORROBORATED, not contradicted. No route disagrees with any other.

Also measured off `preview-config`, and relevant to the paid agent:
`plan.paid = True`, `plan.expired = False`, **`plan.credit_left = 0`**.

---

## 2. What `talent/account/outreach-agent` is

**It answers HTTP 405.** Verbatim, as the client reported it:

```
account_outreach_agent       HTTP 405   FAILED  TalentError: Uplers answered HTTP 405 for talent/account/outreach-agent.
```

405 is Method Not Allowed, **not** 404. That is a meaningful difference and it
is the finding: the route **exists** and is registered in Laravel's router, but
it does not accept GET. It is a **write-only endpoint** (POST/PUT/PATCH/DELETE).

It appears in no prior inventory - not the browser-parity census, not the bundle
call-site audit (`grep` over `_audit/**` returns zero hits for
`account/outreach-agent`).

**It was not probed further, deliberately.** Discovering which verb it accepts
requires sending that verb, and this is a route in the account namespace of a
paid autonomous agent. No non-GET request was sent. What it writes is an open
question for a slice that is scoped to answer it with the operator's consent.

---

## 3. Non-200 routes, verbatim

| route | result |
|---|---|
| `talent/account/outreach-agent` | `HTTP 405` - `TalentError: Uplers answered HTTP 405 for talent/account/outreach-agent.` |

That is the only non-200. The other eight routes all answered **HTTP 200**. No
401, no 403, no 404, no 422, no 429. The session did not lapse during the run.

---

## 4. Per-route results

HTTP status is measured off the transport, not inferred from a successful
return - `get_json` discards the status, so `_StatusRecorder` reads
`status_code` off the response as it passes.

| stem | path | HTTP | envelope `status` | top-level keys | bytes | fixture |
|---|---|---|---|---|---|---|
| `account_status` | `talent/account/status` | 200 | `str` `"success"` | data, jobs, status | 197 | kept |
| `account_outreach_agent` | `talent/account/outreach-agent` | **405** | - | - | - | none |
| `user_me` | `user/me` | 200 | **no `status` key** | agent_tailor_plans, agent_tailor_plans_original, data, happy_referral_total_discount, has_auto_fill_extension_installed, profile_last_updated, resume_tailored_plans, resume_transform_price, tech_attempted, userdata | 14799 | **DELETED (leak)** |
| `outreach_default_templates` | `talent/outreach/default-auto-templates` | 200 | `str` `"success"` | data, status | 2986 | **DELETED (leak)** |
| `outreach_onboard_jobs` | `talent/outreach/onboard-jobs` | 200 | `str` `"success"` | data, status | 62 | kept |
| `outreach_referral_list` | `talent/outreach/referral-list` | 200 | **`int` `200`** | data, message, status | 306 | kept |
| `outreach_value_with_happy` | `talent/outreach/value-with-happy` | 200 | `str` `"success"` | data, status | 2636 | kept |
| `payment_transactions` | `talent/payment-transactions` | 200 | **`int` `200`** | data, message, status | 2795 | kept |
| `outreach_preview_config` | `talent/outreach/preview-config?HR_Number=` | 200 | `str` `"success"` | data, status | 2573 | **DELETED (leak)** |

`HR_Number` for `preview-config` was `HR170725123514`, taken off
`tests/fixtures/talent_pipeline.json` - not fetched.

### The envelope idiom, and the rule that predicts it

This API is inconsistent about `status`, as expected. The inconsistency is not
random - **the two idioms are perfectly separated by the presence of a
`message` key**, across all eight 200s:

- `{"status": "success", "data": ...}` - string, **no** `message` key.
  (`account/status`, `onboard-jobs`, `value-with-happy`,
  `default-auto-templates`, `preview-config`)
- `{"status": 200, "message": "...", "data": ...}` - integer, **always** with a
  `message`. (`referral-list`, `payment-transactions`)

**`user/me` is a third idiom and the one most likely to bite: it has no
top-level `status` key at all.** Code that reads `body["status"]` to decide
success raises `KeyError` on it; code that reads `body.get("status") == 200`
silently treats every successful `user/me` as a failure. Both `talent/*`
idioms are absent there.

---

## 5. Full key lists

### `account_status` - 9 paths

```
$.status
$.data
$.data.gmail
$.data.gmail.id
$.data.gmail.provider
$.data.gmail.status
$.data.gmail.email          [DROP]
$.data.gmail.enc_id
$.jobs
```

### `outreach_onboard_jobs` - 3 paths

```
$.status
$.data
$.data.jobs                 (empty list)
```

### `outreach_referral_list` - 10 paths

```
$.status
$.message
$.data
$.data.referrals            (empty list)
$.data.reward_summary
$.data.reward_summary.reward_mode
$.data.reward_summary.eligible_count
$.data.reward_summary.discount_percent
$.data.reward_summary.maxed_out
$.data.reward_summary.trials_per_reward
```

### `outreach_value_with_happy` - 12 paths

```
$.status
$.data
$.data.response
$.data.response[].reply_category
$.data.response[].reply_type
$.data.response[].company_name
$.data.response[].logo_url
$.data.response[].employee_name    [MASK]
$.data.response[].channel
$.data.jobs_run
$.data.time
$.data.interview_companies
```

### `payment_transactions` - 32 paths

```
$.status
$.message
$.data
$.data.talent_id
$.data.transactions
$.data.transactions.current_page
$.data.transactions.data
$.data.transactions.data[].id
$.data.transactions.data[].talent_id
$.data.transactions.data[].total_amount
$.data.transactions.data[].currency
$.data.transactions.data[].payment_provider
$.data.transactions.data[].status
$.data.transactions.data[].service_type
$.data.transactions.data[].comments
$.data.transactions.data[].payer_name
$.data.transactions.data[].created_at
$.data.transactions.data[].updated_at
$.data.transactions.first_page_url
$.data.transactions.from
$.data.transactions.last_page
$.data.transactions.last_page_url
$.data.transactions.links
$.data.transactions.links[].url
$.data.transactions.links[].label
$.data.transactions.links[].active
$.data.transactions.next_page_url
$.data.transactions.path
$.data.transactions.per_page
$.data.transactions.prev_page_url
$.data.transactions.to
$.data.transactions.total
```

Laravel's standard paginator. 4 transactions, `total: 4`, `per_page: 20`, one
page. One `status: 1` ("Paid", INR 999.00, 2026-08-11) and three `status: 2`
("Payment not completed.", 2499.00 / 999.00 / 2499.00, all 2026-08-11).

### `outreach_default_templates` - 24 paths (fixture deleted)

```
$.status
$.data
$.data.linkedin_template            [MASK]
$.data.linkedin_template[].id
$.data.linkedin_template[].talent_id
$.data.linkedin_template[].provider
$.data.linkedin_template[].message_template
$.data.linkedin_template[].title
$.data.linkedin_template[].active
$.data.linkedin_template[].created_at
$.data.linkedin_template[].updated_at
$.data.linkedin_template[].trashed
$.data.linkedin_template[].resume   [DROP]
$.data.gmail_template               [MASK]
$.data.gmail_template[].id
$.data.gmail_template[].talent_id
$.data.gmail_template[].provider
$.data.gmail_template[].message_template
$.data.gmail_template[].title
$.data.gmail_template[].active
$.data.gmail_template[].created_at
$.data.gmail_template[].updated_at
$.data.gmail_template[].trashed
$.data.gmail_template[].resume      [DROP]
```

Note the shape trap: here `gmail_template` / `linkedin_template` are **lists of
template objects** whose text is at `[].message_template`. In `preview-config`
(below) `gmail_template` is a **single object** whose text is at `.message`.
Same key names, two different shapes, two different routes.

### `outreach_preview_config` - 28 paths (fixture deleted)

```
$.status
$.data
$.data.gmail_template               [MASK]
$.data.gmail_template.message
$.data.gmail_template.subject
$.data.gmail_template.resume_updated
$.data.linkedin_template            [MASK]   (value is null)
$.data.gmail_connected
$.data.linkedin_connected
$.data.plan
$.data.plan.expired
$.data.plan.paid
$.data.plan.positive_replies
$.data.plan.message
$.data.plan.daily_limit_exceeded
$.data.plan.conversion_offer
$.data.plan.credit_plan
$.data.plan.credit_left
$.data.plan.credit_added
$.data.email                        [DROP]
$.data.resumePath
$.data.resumePath.status
$.data.resumePath.url
$.data.resume_name
$.data.hr
$.data.hr.job_title
$.data.hr.company_name
$.data.hr.company_logo
```

### `user_me` - 304 paths (fixture deleted)

Top level: `agent_tailor_plans`, `agent_tailor_plans_original`, `data`,
`happy_referral_total_discount`, `has_auto_fill_extension_installed`,
`profile_last_updated`, `resume_tailored_plans`, `resume_transform_price`,
`tech_attempted`, `userdata`.

`$.data` (33 paths) - the user record:

```
id, name, email [DROP], alt_email, email_verified_at, created_at, updated_at,
last_serving_date, user_type, status, should_re_login, employee_id,
contact_number [DROP], whatsapp_number, skype_id, description, designation,
profile_pic [DROP], talent_id, login_provider_id, login_provider_type,
linkedin_id [DROP], reporting_to, is_tsc, deleted_at, company_id, client_id,
plivo_username, enc_id, short_created_at, user_type_name,
profile_pic_url [DROP]
```

`$.userdata` (first level) - the talent record:

```
name, email [DROP], status, total_experience, contact_number [DROP],
created_at, profile_pic [DROP], user_status, created_through_admin_panel,
last_preference_at, feedback_eligibility, legal_signed, is_deactivated,
recruitment_data, login_provider_type, talent_enc_id, current_ctc [DROP],
expected_ctc [DROP], state, city, job_title, is_product,
product_company_count, has_interview, resume [DROP], resume_data,
resume_review, job_function_id, resume_health, resume_tailored
```

The remaining ~240 paths are the `userdata.resume_health.health_check.
report_details` subtree - an automated resume scoring report with
`sections.{content, format, mandatory_sections, style}`, each leaf carrying
`check` / `points_earned` / `red_flag` / `message`, plus
`file_analyzer_response` and `transform`. Full listing in the run log; it is
schema, not account state, and no part of it is referenced by any tool today.

---

## 6. PII: what happened, and what the masking layer does NOT catch

**Three of the nine fixtures leaked and were deleted by the gate.** They are
not on disk. Field names only below; no values are reproduced.

| stem | what the gate caught |
|---|---|
| `user_me` | suspicious-key at `$.data.whatsapp_number`; suspicious-key at `$.userdata.resume_health.health_check.report_details.sections.mandatory_sections.contact_information.phone` |
| `outreach_default_templates` | linkedin URL at `$.data.gmail_template[0].message_template` |
| `outreach_preview_config` | linkedin URL at `$.data.gmail_template.message` |

The two template leaks are the same cause: his own outreach template text
contains his LinkedIn profile URL inline in the HTML body. `MASK` covers the
key `gmail_template`, but in these two routes the text lives one level deeper
(`[].message_template` and `.message`), so the mask never reaches it.

### Uncaught classes - these need DROP/MASK extended before recapture

I did not edit `capture_outreach.py`; changing the shared DROP/MASK lists
alters behaviour for the two sibling capture scripts and their committed
fixtures, which is outside this slice. Reporting the field names as instructed:

**1. `$.data.resumePath.url` in `preview-config` - a raw resume URL, VERIFIED.**
Measured by shape probe (value never written to disk): a **466-character
`https` URL on host `ats-uplers.s3.amazonaws.com` ending in `.pdf`**. A URL that
long on S3 is presigned, i.e. it is a bearer credential that grants anyone
holding it read access to his resume PDF. `DROP` covers `resume`, `resume_url`,
`original_resume`, `ra_resume_url` - **it does not cover `resumePath`, and the
nested key is just `url`.** Neither the EMAIL nor the LINKEDIN value regex
matches it and `SUSPICIOUS` has no `resume` or `path` term, so **this field
would have been written to disk silently** had the template leak not
independently condemned the same fixture. This is the most serious finding in
this section. Sibling key `$.data.resume_name` is also uncovered.

**2. `$.data.whatsapp_number` in `user/me`** - caught by the `SUSPICIOUS` key
regex, so the gate fires, but it is **not in `DROP`**. The result is a fixture
that can never be captured cleanly: every run writes it, flags it, and deletes
it. It should be added to `DROP` so the route becomes capturable.

**3. `$...contact_information.phone` in `user/me`** - same situation as above,
nested inside the resume-health report.

**4. Uncovered personal keys in `user/me` that nothing flags** - no `DROP`
entry, no `MASK` entry, no `SUSPICIOUS` term:
`$.data.alt_email` (a second email field; it was empty this run, which is the
only reason the EMAIL value regex stayed silent - a populated one would land on
disk), `$.data.skype_id`, `$.data.plivo_username`, `$.userdata.state`,
`$.userdata.city`, `$...report_details.candidate_name`,
`$...health_check.file_name`, `$...health_check.aws_file_name`,
`$...file_analyzer_response.file_name`, and
`$.userdata.resume_health.transform.google_doc_urls` (unverified whether
populated - if it is, it is a second document-URL class alongside `resumePath`).

**5. `$.data.transactions.data[].payer_name` in `payment_transactions` - NOT
treated as a leak, deliberately.** It is the operator's own name. Existing repo
policy already keeps that in fixtures: `tests/fixtures/talent_profile.json`
carries `"name": "G Sundeep"`, `"first_name"`, `"last_name"`. It is also none of
the four categories named in the brief (email, phone, resume URL, token).
Flagging for a ruling rather than acting on it. Same for `$.data.talent_id`.

All five surviving fixtures were swept independently after the run: zero real
email addresses, zero `linkedin.com/in/` hits.

---

## 7. A defect found in the leak gate, and fixed in this script

**The gate's `unlink()` ran AFTER its diagnostic prints, so anything that
killed the process between the two left a leaking fixture on disk.**

This is not hypothetical - it happened during this slice. Run 2 was piped
through `head`, the pipe closed, and `BrokenPipeError` surfaced inside the
key-inventory print of the last route, which had leaked. Python block-buffers
to a pipe, so writes kept succeeding long after the reader was gone and the
failure landed at a flush, well past the point the fixture had been written.
`outreach_preview_config.json` survived on disk **with a real LinkedIn profile
URL in it**, and was removed by hand.

Two things follow:

- `scripts/capture_account_surface.py` now **deletes before it reports**.
  Printing is the only step that can fail for reasons unrelated to the capture,
  so nothing that can fail sits between the leak verdict and the `unlink`.
- **The two sibling scripts still have the original ordering.**
  `capture_outreach.py` and `capture_agent_surface.py` both print first and
  `unlink` afterwards. They are exposed to the same failure. This is the same
  family as the `UnicodeEncodeError` already documented in `leak_summary`'s
  docstring - a diagnostic aborting the job it is diagnosing - but worse,
  because the abort strands PII rather than merely skipping routes. Recommend
  the same reordering there.

---

## 8. Fixture-name collision - needs a ruling

`capture_agent_surface.py` already captures `talent/account/status` and writes
it to **`tests/fixtures/talent_account_status.json`**. This slice's brief
specified the stem `account_status`, so the tree now holds
**`tests/fixtures/account_status.json` as well, and the two files are
byte-identical** (both 197 bytes, verified by `diff`). One of them is
redundant. Choosing which name survives is a call for the lead, not this slice;
flagged rather than resolved.

A useful side effect: the two captures are a day apart (2026-08-23 and
2026-08-24) and identical, so **this reading of the account state is stable
across a day**, not a momentary sample.

---

## 9. State left on disk

Nothing committed. Tree left dirty for review.

New file:
- `scripts/capture_account_surface.py`

New fixtures kept (all swept clean):
- `tests/fixtures/account_status.json` (197 bytes) - duplicate, see section 8
- `tests/fixtures/outreach_onboard_jobs.json` (62 bytes)
- `tests/fixtures/outreach_referral_list.json` (306 bytes)
- `tests/fixtures/outreach_value_with_happy.json` (2636 bytes)
- `tests/fixtures/payment_transactions.json` (2795 bytes)

Deliberately absent (leaked, deleted by the gate):
- `user_me.json`, `outreach_default_templates.json`,
  `outreach_preview_config.json`

Absent (405, no body):
- `account_outreach_agent.json`

Three of the nine routes therefore have **no fixture** and cannot get one until
`DROP`/`MASK` are extended per section 6.
