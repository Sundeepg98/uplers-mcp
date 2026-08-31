# Slice: browser-parity census for the Uplers MCP server

**Question.** What can a human do on the Uplers platform in a browser that this MCP
server cannot do, and for each gap, is it reachable?

**Measured 2026-08-23** against working tree `9b65985`
(`D:\workspace\projects\job-hunting\mcp-servers\uplers`), `server.py` mtime
2026-08-23 09:53, `uplers_server/endpoints.py` mtime 2026-08-23 09:54.

## THE TWO COUNTED ANSWERS

| quantity | count | how it was counted |
|---|---:|---|
| **Tools the server exposes right now** | **47** | `grep -c "@mcp.tool()" server.py` = 47, AST-enumerated to 47 named functions, cross-checked against the 47 `mcp__uplers__*` names on the live MCP connection - the two sets match exactly, name for name. |
| **REACHABLE-GAPs** | **37** | 35 plain GET reads + 2 writes (one reversible toggle, one not recommended). Full list with route, method and parameters in section 4. |

Tier split, measured off the `# THE AUTHENTICATED TIER` banner at `server.py:2141`:
**24 PUBLIC** (defined above it, no account) and **23 AUTHENTICATED** (below it).

Total census rows: **120** (105 numbered capabilities plus 15 lettered ones in section 2.5).
**COVERED 23, REACHABLE-GAP 37, REFUSED 26, BLOCKED 34.** Those four numbers were re-derived by
parsing the census tables in section 2 mechanically, not by hand: 120 rows, no duplicate ids, no
gap in 1-105.

---

## 0. Sources and method

| input | file | what it settled |
|---|---|---|
| tool surface | `D:\workspace\projects\job-hunting\mcp-servers\uplers\server.py` | 47 tools, their tier, and every endpoint constant each one touches (AST walk over `@mcp.tool()`-decorated defs) |
| route rulings | `D:\workspace\projects\job-hunting\mcp-servers\uplers\uplers_server\endpoints.py` | which routes are BUILT vs RECORDED-NOT-BUILT, and the reason attached to each refusal |
| human surface | `D:\workspace\projects\job-hunting\mcp-servers\_audit\_slices\_slice-uplers-route-inventory.md` | 214 API paths, 91 distinct UI paths, 95 router elements, the sidebar item lists |
| request shapes | `D:\workspace\projects\job-hunting\mcp-servers\_audit\_slices\_slice-uplers-shape-followup.md` | eight resolved shape questions, including the full `talent/hr/opportunities` query surface |
| earlier call-site audit | `D:\workspace\projects\job-hunting\mcp-servers\_audit\2026-08-21-uplers-bundle-callsites.md` | shapes for `account/status`, `account/analytics`, `update-saved-hr` |
| consent rulings | `D:\workspace\projects\job-hunting\mcp-servers\uplers\_audit\_slices\_slice-consent-semantics.md` | which route reads back the email-scan consent |
| prior parity pass | `D:\workspace\projects\job-hunting\mcp-servers\_audit\2026-08-22-parity-uplers.md` | the 2026-08-22 state; four of its five UNBUILT items have since shipped |
| scope refusals | `D:\workspace\projects\job-hunting\mcp-servers\uplers\README.md` | the paid-SKU exclusions and the outreach namespace exception |
| live fixtures | `D:\workspace\projects\job-hunting\mcp-servers\uplers\tests\fixtures\*.json` | identifier spaces resolved against real captured payloads (section 6) |

**Read-only.** No `mcp__uplers__*` tool was called, no HTTP request was sent, no file in the
server was modified.

### The classification rule, stated before it is applied

- **COVERED** - a tool already does this.
- **REACHABLE-GAP** - no tool; a plain GET (or an already-reversible write) whose route,
  method AND parameter shape are VERIFIED in the evidence, and which nothing in
  `endpoints.py` or the README refuses.
- **REFUSED** - deliberately not built, with the reason quoted. Recorded, not re-litigated.
- **BLOCKED** - a measurable external reason: paid SKU, irreversible write, needs a browser
  this server does not drive, unresolved identifier space, or unresolved request shape.

Where a route's row in the inventory is marked `GET/POST` and only the POST body was quoted,
the GET's parameters were never extracted. Per the brief's rule that is
**BLOCKED (shape unresolved)**, not REACHABLE. Four rows land there and they are the cheapest
to convert - see section 7.1.

---

## 1. The tool surface - all 47, exactly

### 1.1 PUBLIC tier (24) - no account, no browser, no network after `uplers_sync_index`

| # | line | tool | reads / writes | route or store |
|---:|---:|---|---|---|
| 1 | 169 | `uplers_sync_index` | READ remote + WRITE local index | `GET /api/single-hr-public?hr_number=` + `/sitemap.xml` (`config.RECORD_PATH`, `config.SITEMAP_PATH`) |
| 2 | 208 | `uplers_search_opportunities` | READ local | local sqlite index |
| 3 | 333 | `uplers_get_opportunity` | READ local | local sqlite index |
| 4 | 382 | `uplers_list_new_since` | READ local | local sqlite index |
| 5 | 463 | `uplers_get_market_stats` | READ local | local sqlite index |
| 6 | 778 | `uplers_get_profile` | READ local | `data/profile.json` |
| 7 | 821 | `uplers_set_profile` | WRITE local | `data/profile.json` |
| 8 | 939 | `uplers_assess_fit` | READ local | index + profile, jobcore scoring |
| 9 | 1020 | `uplers_rank_opportunities` | READ local | index + profile |
| 10 | 1162 | `uplers_save_job` | WRITE local | local shortlist table (NOT Uplers' bookmarks) |
| 11 | 1203 | `uplers_list_saved` | READ local | local shortlist table |
| 12 | 1278 | `uplers_unsave_job` | WRITE local | local shortlist table |
| 13 | 1309 | `uplers_track` | WRITE local | local pipeline table |
| 14 | 1338 | `uplers_update_status` | WRITE local | local pipeline table |
| 15 | 1412 | `uplers_list_tracked` | READ local | local pipeline table |
| 16 | 1478 | `uplers_set_alert` | WRITE local | local alerts table (no platform counterpart - see row 96) |
| 17 | 1585 | `uplers_list_alerts` | READ local | local alerts table |
| 18 | 1674 | `uplers_delete_alert` | WRITE local | local alerts table |
| 19 | 1705 | `uplers_daily_brief` | READ local | index + alerts + pipeline |
| 20 | 1764 | `uplers_skill_gap` | READ local | index + profile |
| 21 | 1816 | `uplers_company_intel` | READ local | index |
| 22 | 1909 | `uplers_scheduler_status` | READ local | scheduler state |
| 23 | 1948 | `uplers_config` | READ shared config; WRITE with `write_candidate=True` | `jobhunt.json` via jobcore |
| 24 | 2089 | `uplers_server_info` | READ local | git / build stamp |

### 1.2 AUTHENTICATED tier (23) - reads his account, bearer token from `uplers_login`

| # | line | tool | reads / writes | route |
|---:|---:|---|---|---|
| 25 | 2279 | `uplers_login` | WRITE local token | Playwright window on `LOGIN_URL`; no API route |
| 26 | 2310 | `uplers_auth_status` | READ remote | `GET talent/profile` (`EP_AUTH_PROBE`) |
| 27 | 2354 | `uplers_session_info` | READ remote + local | `EP_AUTH_PROBE` |
| 28 | 2415 | `uplers_logout` | WRITE local token only | none - does NOT call `POST logout` (see row 99) |
| 29 | 2438 | `uplers_my_feed` | READ | `GET talent/hr/opportunities` |
| 30 | 2551 | `uplers_my_pipeline` | READ | `GET talent/hr/my-opportunities` |
| 31 | 2599 | `uplers_get_opportunity_live` | READ | `GET talent/hr/single-hr?hr_number=` |
| 32 | 2642 | `uplers_tailored_jobs` | READ via POST | `POST talent/hr/tailor-jobs {HR_Number}` |
| 33 | 2693 | `uplers_my_profile` | READ | `GET talent/profile` |
| 34 | 2731 | `uplers_compare_profiles` | READ | `GET talent/profile` |
| 35 | 2832 | `uplers_sync_profile_from_uplers` | READ remote, WRITE local | `GET talent/profile` |
| 36 | 3000 | `uplers_my_interviews` | READ | `GET talent/outreach/interview-list?detailed=true` |
| 37 | 3014 | `uplers_my_assessments` | READ | `GET v2/assessments` |
| 38 | 3038 | `uplers_agent_readthrough` | READ x5 | `GET talent/outreach/outreach-step`, `get-outreach-dashboard-data`, `pending-jobs`, `missed-positive-reply-followups`, `agent-tailor-activity` |
| 39 | 3086 | `uplers_platform_saved_jobs` | READ | `GET talent/hr/opportunities?is_saved_filter=1` |
| 40 | 3122 | `uplers_my_preferences` | READ | `GET talent/get-preference` |
| 41 | 3148 | `uplers_assessment_gates` | READ | `GET talent/hr/opportunities` (reads `ai_needed` / `custom_screening_needed` off the rows) |
| 42 | 3193 | `uplers_filter_options` | READ x4 | `GET talent/hr/all-opp-{role,skill,location,company}-master` |
| 43 | 3294 | `uplers_apply` | **WRITE remote, PERMANENT** | `POST talent/hr/intrested` (multipart) |
| 44 | 3377 | `uplers_dismiss` | WRITE remote, reversible | `POST talent/hr/job-not-interested` |
| 45 | 3469 | `uplers_update_profile` | **WRITE remote profile** | `POST talent/profile-upsert {field:"skills", value:[...]}` |
| 46 | 3572 | `uplers_restore_profile` | **WRITE remote profile** | `POST talent/profile-upsert` |
| 47 | 3641 | `uplers_list_profile_snapshots` | READ local | snapshot files on disk |

### 1.3 The complete set of routes this server can emit - 22

MEASURED. Every endpoint constant in `endpoints.py` was counted for references outside that
file, and a regex sweep for inline route literals across `server.py`, `uplers_server/` and
`scripts/` found none in the server itself (only in `scripts/capture_outreach.py`, and all six
of those are routes already built).

Authenticated (20): `talent/hr/opportunities`, `talent/hr/my-opportunities`,
`talent/hr/single-hr`, `talent/hr/tailor-jobs`, `talent/profile`, `v2/assessments`,
`talent/hr/all-opp-role-master`, `-skill-master`, `-location-master`, `-company-master`,
`talent/outreach/interview-list`, `outreach-step`, `get-outreach-dashboard-data`,
`pending-jobs`, `missed-positive-reply-followups`, `agent-tailor-activity`,
`talent/get-preference`, `talent/hr/intrested`, `talent/hr/job-not-interested`,
`talent/profile-upsert`.

Public (2): `single-hr-public`, `sitemap.xml`.

**22 of the 214 inventoried API paths. That is the parity ratio this census is about.**

---

## 2. The census - every human-visible capability, one row

Columns: capability | UI location | API route(s) | server tool | classification.
Evidence for every non-obvious claim is in the row or in the register it points at.

### 2.1 Jobs board and applying

| # | capability | UI location | API route(s) | tool | class |
|---:|---|---|---|---|---|
| 1 | Browse the public catalogue with no account | public job pages | `GET single-hr-public?hr_number=` + `/sitemap.xml` | `uplers_sync_index` + 9 local readers | COVERED |
| 2 | Browse the signed-in jobs board | `/talent/all-opportunities` | `GET talent/hr/opportunities` | `uplers_my_feed` | COVERED |
| 3 | Filter the board on `skills`, `payout`, `maang_plus`, `partner_companies`, `salary_available`, `job_posted_date`, `team_size`, `shifts`, `search` | filter rail, same screen | same route, more params (encoding table: shape-followup Q1 "Bonus") | NONE - `_feed_params` (`server.py:2172`) sends only `pagination`, `page`, `is_count`, `sort_field`, `experience`, `roles`, `locations`, `engagements` | **REACHABLE-GAP** |
| 4 | Sort the board | sort control | `...&sort_field=relevance\|created_at` | `uplers_my_feed(sort=)` | COVERED |
| 5 | In-house positions board | `/talent/inhouse-positions` (sidebar item) | `GET talent/hr/opportunities?...&type=inhouse` | NONE | **REACHABLE-GAP** |
| 6 | Saved Jobs view | sidebar "Saved Jobs" -> `/talent/all-opportunities?is_saved_filter=1` | `GET talent/hr/opportunities?is_saved_filter=1` | `uplers_platform_saved_jobs` | COVERED |
| 7 | Star / unstar a job on Uplers' own board | bookmark button on every job card | `POST talent/hr/update-saved-hr {hr_id:<enc_id>, type:"add"\|"remove"}` | NONE | **REACHABLE-GAP** (reversible write) |
| 8 | Open one job as a signed-in user | `/talent/job/:hrId`, `/talent/all-opportunities/:hrId`, `/talent/opportunities/:hrId` | `GET talent/hr/single-hr?hr_number=` | `uplers_get_opportunity_live` | COVERED |
| 9 | Applied-jobs list with Uplers' own status | `/talent/my-opportunities` (+ `?activeJob=<HR_Number>` deep link) | `GET talent/hr/my-opportunities` | `uplers_my_pipeline` | COVERED |
| 10 | Apply / express interest | "I'm interested" | `POST talent/hr/intrested` | `uplers_apply` | COVERED |
| 11 | See whether you already applied | apply-button state | `GET new-signup/get-apply-status?HR_Number=`; row field `is_applied` | `uplers_apply` re-fetches and refuses a second apply; `is_applied` rides the feed row | COVERED |
| 12 | Mark not interested, and undo it | thumbs-down | `POST talent/hr/job-not-interested` | `uplers_dismiss` | COVERED |
| 13 | "Cancel opportunity" | control never renders | `POST talent/hr/cancel-opportunity` | NONE | REFUSED - R1 |
| 14 | "Jobs like this one" | single-job page | `POST find-similar-job {hr_id:<HR_Number>, user_email}` | NONE | REFUSED - R2 |
| 15 | Per-job match payload | single-job page | `POST talent-matchmake {hr_id:<HR_Number>}` | NONE | REFUSED - R3 |
| 16 | Uplers' server-side tailored suggestions | tailor surface | `POST talent/hr/tailor-jobs {HR_Number}` | `uplers_tailored_jobs` | COVERED |
| 17 | Estimated-salary pill on a job card | job card | `GET get-company-salary-data?hr_id=` | NONE | BLOCKED - B1 |
| 18 | Company detail card on a job | job card | `GET get-company-detail?hr_id=` | NONE | BLOCKED - B2 |
| 19 | Thumbs feedback on the salary estimate | salary pill | `POST company-salary-feedback {hr_id, feedback}` | NONE | BLOCKED - B3 |
| 20 | See a job's screening questions before applying | apply flow | `POST new-signup/get-screening-questions` | NONE | REFUSED - R4 |
| 21 | Answer / save screening questions | apply flow | `POST new-signup/save-screening-questions`, `save-custom-screening-questions` | NONE | BLOCKED - B4 |
| 22 | Record a video answer / video apply | apply flow | `POST talent/video/apply`, `talent/video/store` (multipart) | NONE | BLOCKED - B5 |
| 23 | See which jobs demand an assessment first | job-card badges | fields on `talent/hr/opportunities` rows | `uplers_assessment_gates` | COVERED |
| 24 | Your assessment record | `/talent/assessments` | `GET v2/assessments` | `uplers_my_assessments` | COVERED |
| 25 | Start / assign an assessment | assessment button | `POST talent/hr/assign-assessment {hr_id:<enc_id>}` | NONE | BLOCKED - B6 |
| 26 | Re-take an assessment | assessments screen | `POST talent/assessment/re-test` | NONE | BLOCKED - B6 |
| 27 | Follow an assessment link into the test vendor | `/talent/redirect/link/:assessmentURLID` | browser navigation | NONE | BLOCKED - B7 |

### 2.2 Profile and account

| # | capability | UI location | API route(s) | tool | class |
|---:|---|---|---|---|---|
| 28 | View the real Uplers profile | `/talent/profile`, `/talent/manage-preferences` | `GET talent/profile` | `uplers_my_profile`, `uplers_compare_profiles`, `uplers_sync_profile_from_uplers` | COVERED |
| 29 | Edit the skills list | profile skills editor | `POST talent/profile-upsert {field:"skills", value:[...]}` | `uplers_update_profile`, `uplers_restore_profile`, `uplers_list_profile_snapshots` | COVERED |
| 30 | Edit other profile sections (experience, education, achievements, projects, certifications, testimonials, clienteles) | profile editor | `POST talent/profile` - section-keyed singular envelope | NONE | BLOCKED - B8 |
| 31 | Delete one profile detail | profile editor | `talent/profile/delete-details` | NONE | BLOCKED - B9 |
| 32 | Product-engineering experience section (read) | profile editor | `GET talent/get-product-engineering-experience` (no params) | NONE | **REACHABLE-GAP** |
| 33 | Product-engineering experience (write / delete) | profile editor | `POST talent/store-product-engineering-experience`; `DELETE talent/delete-product-engineering-experience?tid=` | NONE | BLOCKED - B10 |
| 34 | Years-of-experience parsing | profile editor | `GET talent/yoe-parsing` (no params) | NONE | **REACHABLE-GAP** |
| 35 | Upload a profile picture | profile editor | `POST profile/picture` | NONE | BLOCKED - B11 |
| 36 | Public profile preview | `/talent/profile/preview` | `GET profile/preview` (no params) | NONE | **REACHABLE-GAP** |
| 37 | Download your own profile resume | profile / resume surfaces | `GET talent/talent-download-resume-profile?talent_id=` | NONE | **REACHABLE-GAP** |
| 38 | Session bootstrap: who am I, login provider, `enc_id`, `linkedin_id`, profile-completion %, extension installed, snooze state | every screen header | `GET user/me` (no params) | NONE | **REACHABLE-GAP** |
| 39 | Connected-accounts state (Gmail / LinkedIn) as the account screen shows it | `/talent/manage-account` | `GET talent/account/status` (no params) -> `res.data.data.{gmail, linkedin}` | NONE (`uplers_agent_readthrough` reports the AGENT's `step1.gmail_connected` / `linkedin_connected`, a different reading) | **REACHABLE-GAP** |
| 40 | Connect / disconnect Gmail or LinkedIn | `/talent/manage-account`, `/talent/gmail-connect/:token` | `POST talent/account/{gmail,linkedin}/{connect,verify,disconnect}` | NONE | BLOCKED - B12 |
| 41 | Change password | `/talent/change-password/:token` | `POST talent/change-password` | NONE | BLOCKED - B13 |
| 42 | Deactivate / reactivate the account | `/talent/manage-account`, `/talent/reactivate-account` | `POST talent/deactivate-account`, `talent/reactivate-account` | NONE | BLOCKED - B14 |
| 43 | See what Uplers thinks you want | `/talent/manage-preferences` | `GET talent/get-preference` | `uplers_my_preferences` | COVERED |
| 44 | Change the job-search preference | preference screen | `POST user/job-search-preference` | NONE | REFUSED - R5 |
| 45 | Email preference | `/talent/email-preference` | `GET/POST talent/email-preference`; `POST talent/email-preference-update` | NONE | BLOCKED - B15 |
| 46 | Nurture preference | `/talent/nurture-preference` | `GET talent/nurture-preference` (no params) | NONE | **REACHABLE-GAP** |
| 47 | Snooze marketing email (read state) | `/talent/snooze-email` | `GET candidate/snooze-email` (no params) | NONE | **REACHABLE-GAP** |
| 48 | Snooze marketing email (set it) | `/talent/snooze-email` | `POST candidate/snooze-email-update` | NONE | BLOCKED - B16 |
| 49 | Profile-bullet suggestions in the experience editor | profile experience editor | `POST talent/recommendations {key:"rnr", role}` | NONE | REFUSED - R6 |

### 2.3 Resume tooling

| # | capability | UI location | API route(s) | tool | class |
|---:|---|---|---|---|---|
| 50 | Resume health check - run, view report, transform, download | `/talent/resume-health-check`, `/new`, `/:id` | `talent/resume-health-check/*` (16 routes) | NONE | REFUSED - R7 |
| 51 | Pay for a resume health check | `/talent/resume-health-check/:id/payment` | `talent/resume-health-check/{create-order,capture-order,refund-request}` | NONE | REFUSED - R7 |
| 52 | List tailored resumes | `/talent/job-agent/tailor-resume` | `GET talent/tailor/list` (no params) -> `res.data.data.resumes_list` | NONE | REFUSED - R8 |
| 53 | Create / upload / download / match a tailored resume, and its checkout | tailor screens | `talent/tailor/*` (18 routes) | NONE | REFUSED - R8 |
| 54 | Career-coach chat and resume upload | `/talent/career-coach` | `career-coach/*` (7 routes) | NONE | BLOCKED - B17 |
| 55 | Backend resume previewer | `/talent/backend-resume-previewer` | `talent/tailor/match-for-backend`, `talent/resume-transform/download` | NONE | REFUSED - R8 |

### 2.4 The outreach / job-agent sub-app (27 UI screens, ~70 routes)

The standing ruling, quoted in full in R9/G1: **reads are admitted, writes are not.**

| # | capability | UI location | API route(s) | tool | class |
|---:|---|---|---|---|---|
| 56 | Agent dashboard counters | `/talent/outreach-dashboard`, `/talent/job-agent` | `GET talent/outreach/get-outreach-dashboard-data` | `uplers_agent_readthrough` | COVERED |
| 57 | Plan / credits / expiry / auto-run / outreach-mode state | `/talent/job-agent/subscription` | `GET talent/outreach/outreach-step` | `uplers_agent_readthrough` | COVERED |
| 58 | Queue of jobs the agent will work | `/talent/job-agent/pending-jobs` | `GET talent/outreach/pending-jobs` | `uplers_agent_readthrough` | COVERED |
| 59 | Missed positive-reply follow-ups | `/talent/job-agent/missed-replies` | `GET .../missed-positive-reply-followups?days=` | `uplers_agent_readthrough` | COVERED |
| 60 | Agent activity log | `/talent/job-agent/my-activity` | `GET .../agent-tailor-activity` | `uplers_agent_readthrough` | COVERED |
| 61 | Pending-only view of missed follow-ups | `/talent/job-agent/missed-replies` | `GET .../missed-positive-reply-followups-pending?days=N` | NONE | **REACHABLE-GAP** |
| 62 | The agent's own recommended-jobs feed | `/talent/job-agent/recommended-jobs` | `GET .../get-recommended-jobs?limit=N` | NONE | **REACHABLE-GAP** |
| 63 | Email-sourced recommended jobs, with the plan quota | `/talent/job-agent/recommended-jobs` | `GET .../recommended-jobs-email?best_for_you=true\|false` | NONE | **REACHABLE-GAP** |
| 64 | Email-scan consent state and last-scan metadata | recommended-jobs screen | `GET .../recommended-jobs-meta-email` (no params) | NONE | **REACHABLE-GAP** |
| 65 | Grant / revoke the Gmail job scan | recommended-jobs toggle | `POST` / `DELETE talent/outreach/consent-email-job-scan` | NONE | REFUSED - R10 |
| 66 | Grant auto-run consent | agent configure | `POST .../consent-auto-run {consent}` | NONE | REFUSED - R9 |
| 67 | Ask the agent to run a job now | recommended-jobs / dashboard | `POST .../auto-run-request {job_id, source}` | NONE | REFUSED - R9, R11 |
| 68 | Onboarding job set | agent onboarding | `GET .../onboard-jobs` (no params) -> `.data.jobs` | NONE | **REACHABLE-GAP** |
| 69 | Message templates in use | `/talent/job-agent/configure?tab=message-templates` | `GET .../get-message-templates` (no params) | NONE | **REACHABLE-GAP** |
| 70 | Default auto templates | same screen | `GET .../default-auto-templates` (no params) | NONE | **REACHABLE-GAP** |
| 71 | Save / rewrite / refine a message template | same screen | `POST .../store-message-template`, `rewrite-message`, `refine-message` | NONE | REFUSED - R9 |
| 72 | Auto-reply settings (read) | agent configure | `GET .../get-auto-reply` (no params) | NONE | **REACHABLE-GAP** |
| 73 | Change auto-reply settings | agent configure | `POST .../update-auto-reply {hours, handle_auto_reply, auto_reply_categories}` | NONE | REFUSED - R9 |
| 74 | Follow-up settings (read) | `/talent/job-agent/configure?tab=follow-up-settings` | `GET talent/outreach/settings/followup` | NONE | BLOCKED - B18 |
| 75 | Change follow-up settings | same | `POST .../settings/followup {disabled_followup_gmail, disabled_followup_linkedin, interval_days, interval_days_gmail, ...}` | NONE | REFUSED - R9 |
| 76 | Blocked / disabled companies list (read) | `/talent/outreach-settings`, `/talent/job-agent/follow` | `GET talent/outreach/settings/disabled-companies` | NONE | BLOCKED - B19 |
| 77 | Add / remove a blocked company | same | `POST .../settings/disabled-companies {company_id}`; `DELETE .../settings/disabled-companies/{id}` | NONE | REFUSED - R9 |
| 78 | Company autocomplete for the block list | same | `GET talent/outreach/settings/companies?search=` | NONE | **REACHABLE-GAP** |
| 79 | Outreach agent meta | `/talent/job-agent/job-applications`, `/talent/outreach-dashboard` | `GET .../get-outreach-agent-meta` (no params) | NONE | **REACHABLE-GAP** |
| 80 | Per-run outreach agent record | same screens | `GET .../get-outreach-agent?<param not captured>` | NONE | BLOCKED - B20 |
| 81 | People the agent contacted for one job | `/talent/job-agent/outreach-request/:outreach_hr_id` | `GET .../outreached-people?outreach_hr_id=` | NONE | **REACHABLE-GAP** |
| 82 | Employee contact requests for one job | `/talent/verify-outreach-person/:outreach_hr_id` | `GET .../get-employee-requests?outreach_hr_id=` | NONE | **REACHABLE-GAP** |
| 83 | Reveal a contact's email | verify-outreach-person | `POST .../reveal-email {outreach_hr_id, outreach_employee_id}` | NONE | REFUSED - R9 |
| 84 | Submit contact requests | verify-outreach-person | `POST .../store-employee-requests {outreach_hr_id, persons:[...]}` | NONE | REFUSED - R9 |
| 85 | Discard a job from the agent queue | agent screens | `POST .../discard-job {outreach_hr_id, feedback_reason, feedback_text}` | NONE | REFUSED - R9 |
| 86 | Outreach config preview for one job | outreach-request screen | `GET .../preview-config?HR_Number=` | NONE | **REACHABLE-GAP** |
| 87 | Job description for an agent job | agent job screens | `GET .../job-description?id=` | NONE | BLOCKED - B21 |
| 88 | Interview list | `/talent/job-agent/interview-list` | `GET .../interview-list?detailed=true` | `uplers_my_interviews` | COVERED |
| 89 | Submit interview feedback | `/talent/job-agent/interview-list` | `POST .../interview-feedback` | NONE | REFUSED - R12 |
| 90 | "Schedule interview" / "View slot" / "Review my interview" | applied-job cards, sidebar (gated on `has_interview`) | none - `/talent/my-interviews` and `/talent/interview-feedbacks` are not registered routes | NONE | BLOCKED - B22 |
| 91 | Apply to an external job by pasting a URL | `/talent/outreach-external-job-link`, `/talent/job-agent/external-jobs` | `POST talent/referral-agent/job-apply-by-link {url}`; `job-apply-by-links-batch` | NONE | REFUSED - R13 |
| 92 | External job-link quota used today | same screens | `GET .../external-job-links-today` (no params) | NONE | **REACHABLE-GAP** |
| 93 | External job-link quota remaining | same screens | `GET .../external-job-link-remaining` (no params) | NONE | **REACHABLE-GAP** |
| 94 | External-apply pending jobs | `/talent/job-agent/external-jobs` | `GET .../get-external-apply-pending-jobs` (no params) | NONE | **REACHABLE-GAP** |
| 95 | Remove an external pending job | same | `DELETE .../external-apply-pending-jobs/?external=` | NONE | REFUSED - R9 |
| 96 | Is any manual action pending | agent dashboards | `GET .../has-pending-action-manual-outreach-agent` (no params) | NONE | **REACHABLE-GAP** |
| 97 | Last resume-health-check state, as the agent screens show it | agent screens | `GET .../get-last-health-check` (no params) | NONE | **REACHABLE-GAP** (adjacency flagged - see section 4 note) |
| 98 | Agent plans and pricing | `/talent/job-agent/subscription`, `/upgrade` | `GET .../agent-plans` (no params) | NONE | **REACHABLE-GAP** |
| 99 | Payment history | `/talent/job-agent/payments` | `GET talent/payment-transactions` (no params) | NONE | **REACHABLE-GAP** |
| 100 | Claim a discount, extend the trial, claim a light plan, act on the subscribe modal | subscription screens | `POST .../claim-discount-offer`, `extend-free-trial`, `claim-custom-light-plan`, `subscribe-modal-action` | NONE | BLOCKED - B23 |
| 101 | Referral list and reward summary | `/talent/referral-ai-agent`, `/talent/referral-fast-track` | `GET .../referral-list` (no params) -> `referrals`, `reward_summary`, `status` | NONE | **REACHABLE-GAP** |
| 102 | Invite friends, claim / verify a referral code | referral screens | `POST .../invite-to-multiple-friends`, `claim-referral-code`, `verify-referral-code` | NONE | REFUSED - R9 |
| 103 | "Value with Happpy" summary panel | agent marketing panel | `GET .../value-with-happy` (no params) -> `res.data.data` | NONE | **REACHABLE-GAP** |
| 104 | Raise a support query | `/talent/job-agent/need-help`, `/talent/get-a-help` | `GET/POST talent/outreach/support` | NONE | BLOCKED - B24 |
| 105 | The `user.outreach` entitlement block (`is_eligible`, `is_outreach_paid`, `payment_received`, `outreach_plan_validity`, `onboarding_phase`, `account_connected`, `disabled_tailor`) | every agent screen, via redux | only carried by `POST talent-pages-tracking` -> `res.data.session_data.outreach` | NONE | BLOCKED - B25 |

### 2.5 Notifications, alerts, inbox, auth lifecycle, master data

| # | capability | UI location | API route(s) | tool | class |
|---:|---|---|---|---|---|
| 106a | Notifications centre | none | none | NONE | BLOCKED - B26 |
| 106b | Server-side job alerts | none | none | `uplers_set_alert` / `list_alerts` / `delete_alert` are LOCAL only | BLOCKED - B26 |
| 106c | Recruiter inbox / messaging | none | `talent/account/gmail/inbox/send` (0 HTTP sites) | NONE | BLOCKED - B27 |
| 106d | Sign in | `/login`, `/talent/joinus` | browser; bearer token from `localStorage["token"]` | `uplers_login`, `uplers_auth_status`, `uplers_session_info` | COVERED |
| 106e | Sign out on the server (not just locally) | header menu | `POST logout {}` | `uplers_logout` deletes the local token only | **REACHABLE-GAP** (NOT RECOMMENDED) |
| 106f | Register / verify OTP / SSO / set password | signup screens | `new-signup/*`, `login-sso`, `otp-*`, `set-password-ats`, `store-password-ats`, `joinus`, `registration` | NONE | BLOCKED - B28 |
| 106g | Chrome-extension install / login | `/talent/extension-login`, `/talent/extension-install-success` | `POST talent/store-extension-installed`, `talent/tailor/store-extension-uninstall`, `.../extension-engagement` | NONE | BLOCKED - B29 |
| 106h | NPS feedback survey | `/talent/nps/feedback` | `POST nps/feedback`, `nps/feedback-quetions` | NONE | BLOCKED - B30 |
| 106i | Resolve a short link from an email | `/talent/r/:shortURL`, `/talent/link/:uid`, `/talent/redirect(/:uid)` | `POST get-original-url {code}` | NONE | BLOCKED - B31 |
| 106j | Role / skill / location / company filter options | filter rail | `GET talent/hr/all-opp-*-master` | `uplers_filter_options` | COVERED |
| 106k | Job-function master list | profile / preference dropdowns | `GET job-functions-master` (no params) -> `.data.data` | NONE | **REACHABLE-GAP** |
| 106l | Global location master | profile / preference dropdowns | `GET common/location-master` (no params) | NONE | **REACHABLE-GAP** |
| 106m | Skill autocomplete | skills editor | `GET search/skills?q=<term>&status=1` | NONE | **REACHABLE-GAP** |
| 106n | Skill spelling autocorrect | skills editor | `POST skills/autocorrect {text}` | NONE | REFUSED - R4 |
| 106o | Telemetry the UI emits invisibly | every screen | `link-tracking`, `profile-tracking`, `talent-pages-tracking`, `talent/mixpanel-tracking`, `talent/outreach/track-journey`, `registration-logs`, `talent/associate`, `talent/add-video-count`, `hr/*-video-counter-store` | NONE | BLOCKED - B32 |

(Rows 106a-106o are lettered so the numeric row count stays at 106 capabilities.)

---

## 3. Count reconciliation

Derived by parsing the section-2 tables mechanically (regex over the row-id column and the
classification column), not by hand.

| class | rows | distinct reasons | row ids |
|---|---:|---:|---|
| COVERED | 23 | - | 1, 2, 4, 6, 8, 9, 10, 11, 12, 16, 23, 24, 28, 29, 43, 56, 57, 58, 59, 60, 88, 106d, 106j |
| REACHABLE-GAP | **37** | 37 (G1-G37) | 3, 5, 7, 32, 34, 36, 37, 38, 39, 46, 47, 61, 62, 63, 64, 68, 69, 70, 72, 78, 79, 81, 82, 86, 92, 93, 94, 96, 97, 98, 99, 101, 103, 106e, 106k, 106l, 106m |
| REFUSED | 26 | 13 (R1-R13) | 13, 14, 15, 20, 44, 49, 50, 51, 52, 53, 55, 65, 66, 67, 71, 73, 75, 77, 83, 84, 85, 89, 91, 95, 102, 106n |
| BLOCKED | 34 | 32 (B1-B32) | 17, 18, 19, 21, 22, 25, 26, 27, 30, 31, 33, 35, 40, 41, 42, 45, 48, 54, 74, 76, 80, 87, 90, 100, 104, 105, 106a, 106b, 106c, 106f, 106g, 106h, 106i, 106o |

23 + 37 + 26 + 34 = **120 rows**, which is 105 numbered capabilities plus the 15 lettered rows
in section 2.5. Rows outnumber reasons in the REFUSED and BLOCKED columns because several rows
share one ruling (e.g. rows 50, 51 both cite R7; rows 25, 26 both cite B6).

**The two numbers the brief asks for are 47 and 37. Both are exact, both are derived: 47 from
an AST walk cross-checked against the live MCP tool list, 37 from a regex parse of the census
tables cross-checked against the independently numbered G1-G37 list in section 4.**

---

## 4. THE 37 REACHABLE-GAPS - one line each, with route, method, parameters

Ranked: high value first, then the plumbing, then the two writes.

### 4.1 High value for a working job hunt (11)

| # | route | method | parameters | what it gets you |
|---:|---|---|---|---|
| G1 | `talent/outreach/get-recommended-jobs` | GET | `?limit=<int>` (bundle passes 4, 10, 15) | the agent's own personalised job feed - the closest thing to a recommendation engine on this API, distinct from `talent/recommendations` |
| G2 | `talent/outreach/recommended-jobs-email` | GET | `?best_for_you=true\|false` (the only two values) | agent-sourced jobs plus `res.data.breakdown` and `res.data.plan.limit` - the subscription quota |
| G3 | `talent/outreach/recommended-jobs-meta-email` | GET | none | `has_consent`, `gmail_connected`, `gmail_email`, `last_job_scan`, `total_jobs`, `breakdown`, `best_for_you_breakdown`, `best_for_you_count`, `job_function_name`. This is the route the platform itself re-reads after a consent write, and it answers the open interview-consent question WITHOUT performing the refused write |
| G4 | `talent/hr/opportunities` | GET | the 9 filter params the tool does not send: `skills`, `payout`, `maang_plus`, `partner_companies`, `salary_available`, `job_posted_date`, `team_size`, `shifts`, `search` (encodings in shape-followup Q1 "Bonus") | the rest of the board's filter rail. Existing route, existing tool - parameter work, not a new endpoint |
| G5 | `talent/hr/opportunities` | GET | `...&type=inhouse` | the in-house positions board, a first-class sidebar item with its own 250-row-adjacent cohort |
| G6 | `talent/outreach/agent-plans` | GET | none | `agent_tailor_plans`, `agent_tailor_plans_original`, `conversion_offer`, `happy_referral_total_discount` - plan and credit state |
| G7 | `talent/payment-transactions` | GET | none | what he has actually paid Uplers |
| G8 | `talent/outreach/outreached-people` | GET | `?outreach_hr_id=<id>` | who the agent actually contacted for a job. **Identifier resolved:** `outreach_hr_id` is a column on `agent-tailor-activity` rows, which `uplers_agent_readthrough` already reads (measured, section 6) |
| G9 | `talent/outreach/get-employee-requests` | GET | `?outreach_hr_id=<same>` | contact requests awaiting his verification |
| G10 | `talent/account/status` | GET | none | `res.data.data.{gmail, linkedin}` - the account screen's own view of connected accounts. `EP_ACCOUNT_STATUS` is already declared under `--- Reads ---` in `endpoints.py:55` and referenced by nothing |
| G11 | `user/me` | GET | none | the richest single response in the bundle: `profile_completion_percentage`, `userdata`, `data.enc_id`, `data.login_provider_type`, `data.linkedin_id`, `tech_attempted`, `snooze_modal_vis`, `snooze`, `has_auto_fill_extension_installed` |

### 4.2 Agent surface, useful but secondary (12)

| # | route | method | parameters |
|---:|---|---|---|
| G12 | `talent/outreach/missed-positive-reply-followups-pending` | GET | `?days=<int>` (bundle passes 15) |
| G13 | `talent/outreach/get-message-templates` | GET | none |
| G14 | `talent/outreach/default-auto-templates` | GET | none |
| G15 | `talent/outreach/get-auto-reply` | GET | none -> `.data.data`, `res.data.status` |
| G16 | `talent/outreach/get-outreach-agent-meta` | GET | none -> `.data.data`, `res.data.status` |
| G17 | `talent/outreach/onboard-jobs` | GET | none -> `.data.jobs`, `res.data.message` |
| G18 | `talent/outreach/get-external-apply-pending-jobs` | GET | none |
| G19 | `talent/outreach/external-job-links-today` | GET | none |
| G20 | `talent/outreach/external-job-link-remaining` | GET | none |
| G21 | `talent/outreach/has-pending-action-manual-outreach-agent` | GET | none (response discarded by the UI, so the envelope is unknown until called) |
| G22 | `talent/outreach/preview-config` | GET | `?HR_Number=<HR_Number>` |
| G23 | `talent/outreach/settings/companies` | GET | `?search=<term>` |

### 4.3 Profile, referral and master-data plumbing (12)

| # | route | method | parameters |
|---:|---|---|---|
| G24 | `talent/talent-download-resume-profile` | GET | `?talent_id=<talent_details.id>` - **identifier resolved** (section 6). Shape-followup Q6: "free read of an artifact the operator owns... No payment gate anywhere on this path" |
| G25 | `talent/outreach/referral-list` | GET | none -> `res.data.referrals`, `res.data.reward_summary`, `res.data.status` |
| G26 | `talent/get-product-engineering-experience` | GET | none - a profile section this server does not read |
| G27 | `talent/nurture-preference` | GET | none |
| G28 | `profile/preview` | GET | none (the UI discards the response, so the envelope is unknown until called) |
| G29 | `talent/yoe-parsing` | GET | none |
| G30 | `candidate/snooze-email` | GET | none |
| G31 | `job-functions-master` | GET | none -> `.data.data` |
| G32 | `common/location-master` | GET | none |
| G33 | `search/skills` | GET | `?q=<term>&status=1` |
| G34 | `talent/outreach/value-with-happy` | GET | none -> `res.data.data` |
| G35 | `talent/outreach/get-last-health-check` | GET | none -> `.data.data`. **ADJACENCY FLAGGED, your call:** it sits under the outreach prefix whose READS are admitted, but its subject is the resume-health SKU the README refuses by name. Recorded, not decided. |

### 4.4 The two writes (2)

| # | route | method | body | note |
|---:|---|---|---|---|
| G36 | `talent/hr/update-saved-hr` | POST | `{hr_id: <job.enc_id>, type: "add" \| "remove"}` -> `res.data.status === "success"` | The star on Uplers' own board. **Explicitly a reversible toggle** - `"add"` / `"remove"` are the only two values, VERIFIED across 16 call sites (2026-08-21 audit sec. 14). `enc_id` is on every feed row (measured, section 6). `uplers_platform_saved_jobs` already reads this list; this is the write half. `endpoints.py` records the shape at line 158 and attaches **no reason** for not building it; the 2026-08-22 parity pass said "report-and-stop", which is an escalation, not a refusal. |
| G37 | `logout` | POST | `{}` | **NOT RECOMMENDED.** Technically reachable and reversible (you can sign in again), and `uplers_logout` today only deletes the local token. Building it would end the session every authenticated tool depends on, for no read benefit. Listed for completeness, so the count is honest. |

**Sub-counts if you want them narrower:** 35 plain GET reads (G1-G35), 1 reversible write
(G36), 1 not-recommended write (G37). If G4 (parameter work on an existing route) and G37 are
both excluded, the buildable-new-read count is **34**.

---

## 5. Registers

### 5.1 REFUSED - the rulings, quoted. Recorded, not re-litigated.

**R1 - `talent/hr/cancel-opportunity`.** `endpoints.py:157`: `# POST JSON, dead code in this
build`. README: *"Its name says 'withdraw'. It is not that, and shipping it as one would be the
most dangerous kind of wrong - it would imply an undo that does not exist."* Plus: *"Its one
call site is unreachable... gated on `opportunityType === 'matched'`, and `'matched'` is never
passed as that prop anywhere in the 86 files."*

**R2 - `find-similar-job`.** `endpoints.py:206-231`, three reasons verbatim:
*"1. It would put the FIRST non-write POST into a server whose write-surface census (2
requisition writes, 2 profile writes, 1 config write) is a load-bearing safety artefact. A
census that starts admitting POSTs 'because that one is really a read' stops being a census.
2. It sends HIS EMAIL ADDRESS in the body to get back a list.
3. The payoff is near zero here. This server already indexes all 250 requisitions locally..."*
**See finding F3 in section 7 - reason 1's premise is contradicted by the same file.**

**R3 - `talent-matchmake`.** Recorded in the same block, `endpoints.py:232`.

**R4 - read-shaped POSTs generally** (`new-signup/get-screening-questions`,
`skills/autocorrect`). Not named individually anywhere. Refused by the general principle stated
in R2: *"A census that starts admitting POSTs 'because that one is really a read' stops being a
census."* **Flagged as an inherited ruling, not an explicit one** - if you rule the other way,
these two rows move to REACHABLE and the count becomes 39.

**R5 - `user/job-search-preference`.** `endpoints.py:122-123`: *"Its sibling
`user/job-search-preference` is a real WRITE that changes how he appears to recruiters. Not
built, and not to be confused with this."*

**R6 - `talent/recommendations`.** README: *"`talent/recommendations` is not a
job-recommendations feed. Despite the name, its body is `{key: 'rnr', role: '<job title>'}` and
its single caller in 13.4 MB is the profile experience editor - it returns suggested
bullet-point text for a CV entry. Building it as a jobs feed would have produced a tool that
silently returned the wrong kind of thing."*

**R7 - `talent/resume-health-check/*`** (16 routes). README "Deliberately out of scope":
*"No resume tailoring, no resume health check... Those endpoints... are Uplers' own paid
candidate products... Reimplementing a paid product for free against a marketplace whose value
is a human recruiter advocating for you is a bad trade."*

**R8 - `talent/tailor/*`** (18 routes). Same README ruling as R7. Shape-followup Q6 adds that
`tailor/list` itself is a free GET but *"the SCREEN behind it is gated, and the tailored
artifacts it lists are produced by the paid checkout."*

**R9 - every WRITE under `talent/outreach/*`.** `endpoints.py:98-102`: *"THE LINE IS READS
ONLY, and it is a hard one. The write half of this namespace stays unbuilt:
`interview-feedback`, `consent-email-job-scan`, and anything that would make a SECOND agent
apply from one account. He already has an applier; a second uncoordinated one against a
250-requisition board where apply is permanent is the wrong answer."* README: *"Six routes
under it are now read, and none is written."*

**R10 - `talent/outreach/consent-email-job-scan`.** `endpoints.py:234-241`: *"This is the route
that flips it - and it is a WRITE, in the excluded `talent/outreach/*` namespace, that changes
what Uplers reads on his behalf. His call, not this server's."*

**R11 - a second autonomous applier.** README: *"What that emphatically does not license is
building a second applier... a second uncoordinated agent applying from one account, against a
250-requisition board, through a single intermediary who gates every future match, while the
vendor's own agent already holds the wheel, is the wrong answer at any quality of
implementation."*

**R12 - `talent/outreach/interview-feedback`.** `endpoints.py:83-84`: *"The write half of the
pair (`talent/outreach/interview-feedback`) is deliberately NOT built."*

**R13 - `talent/referral-agent/*`.** README "Deliberately out of scope" names the prefix.
`job-apply-by-link` additionally hands an arbitrary external job URL to the paid agent, which
is R11 by another door.

### 5.2 BLOCKED - the measured reasons

**B1 / B2 / B3 - `get-company-salary-data`, `get-company-detail`, `company-salary-feedback`
(shape unresolved: identifier space).** `endpoints.py:195-202`: *"on 2026-08-22 six live GETs
(HR_Number / numeric id / enc_id, against one closed and one open requisition) every one
answered `{"status":400,"errors":"No HR found.."}`. **No 403 was ever observed, so the
entitlement question is UNTESTED, not answered** - what is unknown is which identifier space
`hr_id` names here. It is not any of the three this API uses elsewhere."* Do not re-run those
six probes.

**B4 - screening-question writes.** Body recorded only as the minified token `e`; and the write
is a limb of `talent/hr/intrested`, which is permanent.

**B5 - video apply.** `multipart/form-data` body shape never extracted, and the capture is a
browser media surface this server does not drive.

**B6 - `talent/hr/assign-assessment`, `talent/assessment/re-test`.** Writes that create a real
assessment attempt on his account. That the pair exists at all - a separate `re-test` route
rather than a cancel - is the evidence there is no undo.

**B7 - `/talent/redirect/link/:assessmentURLID`.** Navigation into a third-party test vendor
(the bundle's non-URL constants include `"AiInterview"` and `["TestGorilla"]`). This server
drives no browser after `uplers_login`.

**B8 - other profile sections via `POST talent/profile`.** The one call site is URL-parametric
by design (inventory C.0.1: the generic profile poster takes its URL as a function parameter),
and no per-section body was ever extracted. Section-keyed singular envelopes are described
(`{experience: {...}}`, `{achievmentsNew: {...}}`) but not quoted per section.

**B9 - `talent/profile/delete-details`.** Inventory A.1: *"genuinely defined-but-unwired - no
HTTP site, no wrapper"*. Zero HTTP sites in 13.4 MB, so no shape exists to copy.

**B10 - product-engineering experience writes.** `POST` body recorded only as `e`; the DELETE
takes `?tid=` whose space is unnamed.

**B11 - `profile/picture`.** Multipart upload, browser file picker.

**B12 - Gmail / LinkedIn connect and disconnect.** The handshake completes in a browser
redirect (`/talent/gmail-connect/:token`); bodies recorded only as `e` / `null!=e?e:{}`.

**B13 - `talent/change-password`.** Credential write; body recorded only as `e`.

**B14 - `talent/deactivate-account`, `talent/reactivate-account`.** Account-destructive.

**B15 - `talent/email-preference` (shape unresolved).** Inventory row is `GET/POST`, 2 sites,
and the only quoted params/body is `e` - the POST's. The GET's parameters were never extracted.

**B16 - `candidate/snooze-email-update`.** Write; body recorded only as `e`.

**B17 - `career-coach/*`.** A separate auth realm: every call site attaches
`Authorization: "Bearer " + localStorage.getItem("cc_token")`, and that token is minted by
`POST career-coach/create-guest-user`. Reading requires performing a write to obtain a token
this server does not hold.

**B18 - `talent/outreach/settings/followup` GET (shape unresolved).** `GET/POST`, 6 sites; only
the POST body is quoted. See 7.1 - this is one grep from REACHABLE.

**B19 - `talent/outreach/settings/disabled-companies` GET (shape unresolved).** Same pattern:
`GET/POST`, 6 sites, only `{company_id}` (the POST body) quoted. See 7.1.

**B20 - `talent/outreach/get-outreach-agent?` (shape unresolved).** The constant itself ends in
a bare `?`, so a query parameter exists whose name was never captured.

**B21 - `talent/outreach/job-description?id=` (shape unresolved).** The param name is `id`, but
which of the four identifier spaces it names is not stated, and it is none of the three in
`IDENTIFIER_SPACES`.

**B22 - "Schedule interview" / "View slot" / "Review my interview".** The human cannot do this
either. Inventory D.5, complete negative search: *"occurrences of `path:"...my-interviews"`
across all 86 files: 0 ... `path:"...interview-feedbacks"`: 0"*, while both are rendered as
live links. INFERRED (strong) by that slice: those buttons land on the `*` -> 404 component.

**B23 - subscription commerce writes.** `claim-discount-offer`, `extend-free-trial`,
`claim-custom-light-plan`, `subscribe-modal-action` all alter a live paid subscription.

**B24 - `talent/outreach/support` (shape unresolved).** `GET/POST`, 3 sites; the GET's params
were never extracted, and the POST half is R9.

**B25 - the `user.outreach` entitlement block (read only obtainable through a write).**
Shape-followup Q7: the fields `is_eligible`, `is_outreach_paid`, `payment_received`,
`outreach_plan_validity`, `onboarding_phase`, `account_connected`, `disabled_tailor` ride on
`POST talent-pages-tracking -> res.data.session_data.outreach` and on no GET anywhere. The
second entitlement surface (`plan`, `has_plan_expired`, `credit_plan`, `credit_left`) IS a GET
and is already covered by `uplers_agent_readthrough`.

**B26 - notifications and platform-side alerts do not exist.** MEASURED, complete negative
search over the 214-path inventory: `notification` -> **0 occurrences**, `alert` -> **0
occurrences**. There is no surface to be behind. The nearest neighbours are
`talent/email-preference`, `talent/nurture-preference` and `candidate/snooze-email`.

**B27 - recruiter inbox.** `talent/account/gmail/inbox/send` is the only inbox-shaped route in
214, and inventory A.1 records it as *"genuinely defined-but-unwired - no HTTP site, no
wrapper"*. Dead in his browser too.

**B28 - registration / OTP / SSO / password-set cluster.** Account-creation and credential
writes; and inventory A.2 shows six of them (`sso`, `profile/sso`, `otp-verify`,
`otp-validity-check`, `registration`, `talent/store-password`) have **zero** UI calls - a
superseded signup path.

**B29 - Chrome-extension surface.** This server does not run a browser extension.

**B30 - `nps/feedback`.** A write of survey responses on his behalf; no read half.

**B31 - `get-original-url`.** A read-shaped POST (R4) whose `{code}` only ever arrives inside
an email link.

**B32 - telemetry.** `link-tracking`, `profile-tracking`, `talent-pages-tracking`,
`talent/mixpanel-tracking`, `talent/outreach/track-journey`, `registration-logs`,
`talent/associate`, `talent/add-video-count`, `hr/*-video-counter-store`,
`talent/outreach/extension-engagement` are writes that exist to report the human's behaviour.
Not a user-facing capability. `talent-pages-tracking` is the exception worth remembering - see
B25.

---

## 6. Identifier spaces - what this census resolved, measured against live fixtures

`endpoints.py:264-272` names three spaces (`id`, `enc_id`, `HR_Number`) and warns that getting
them wrong is *"the most likely silent bug in any client of this API"*. Three questions that
gate REACHABLE-GAPs were open; two are now closed by measurement against captured payloads.

| identifier | question | measurement | verdict |
|---|---|---|---|
| `enc_id` | is it available to a client that wants to call `update-saved-hr`? | `tests/fixtures/talent_feed.json` - every one of the 86 keys on a feed row was enumerated; `enc_id` (str) and `id` (int) and `HR_Number` (str) are all present, alongside `is_saved` and `saved_hr_id` | **RESOLVED** - G36 is callable from a row this server already reads |
| `talent_id` | which field feeds `talent-download-resume-profile?talent_id=` | `tests/fixtures/talent_profile.json` - a recursive walk found exactly **one distinct** `talent_id` value anywhere in the payload, and it equals `talent_details.id`. It is NOT `talent_details.user_id` | **RESOLVED** - G24 is callable |
| `outreach_hr_id` | a fourth space; where does a client get one? | `tests/fixtures/outreach_tailor_activity.json` - all 48 `data.list` rows carry `outreach_hr_id`, plus `hr_enc_id` and `HR_Number` | **RESOLVED** - G8 and G9 are callable from `agent-tailor-activity`, which `uplers_agent_readthrough` already reads |
| `hr_id` on `get-company-salary-data` / `get-company-detail` | which space? | six live GETs on 2026-08-22 across all three known spaces returned `{"status":400,"errors":"No HR found.."}` | **STILL UNRESOLVED** - B1/B2/B3 stand |
| `id` on `talent/outreach/job-description` | which space? | never stated in the evidence | **UNRESOLVED** - B21 |

---

## 7. Findings I am escalating rather than acting on

These are inconsistencies between the census inputs. I recorded them; I did not fix, re-litigate
or route around any of them.

**F1 - `endpoints.py` files a BUILT route under "Recorded, deliberately NOT built".**
`QP_IS_SAVED_FILTER` is at `endpoints.py:186`, below the section banner at line 160-164 which
reads: *"# --- Recorded, deliberately NOT built --- # Shapes kept here so the findings are not
lost. No tool calls any of these."* MEASURED: the constant has **7 references outside
`endpoints.py`** (`uplers_server/saved_filter.py` x6, and `uplers_platform_saved_jobs` at
`server.py:3086` sends it). The banner sentence "No tool calls any of these" is false as of the
2026-08-23 build. The other four constants under that banner (`EP_COMPANY_SALARY`,
`EP_COMPANY_DETAIL`, `EP_FIND_SIMILAR_JOB`, `EP_TALENT_MATCHMAKE`, `EP_CONSENT_EMAIL_JOB_SCAN`)
do have zero outside references, so the banner is right about them and wrong only about the
one that shipped.

**F2 - the "--- Writes ---" section header is stale the same way.** `endpoints.py:131` reads
`# --- Writes (shapes recorded; only job-not-interested is built) ------------`. MEASURED
outside-references: `EP_NOT_INTERESTED` 2, `EP_INTRESTED` 2 (`uplers_apply`),
`EP_PROFILE_UPSERT` 4 (`uplers_update_profile`, `uplers_restore_profile`). Three of the five
constants in that block are built, not one. `EP_CANCEL_OPPORTUNITY` and `EP_UPDATE_SAVED_HR`
are the two that are genuinely unbuilt.

**F3 - the first stated reason for refusing `find-similar-job` is contradicted by the same
file.** `endpoints.py:218-221` argues: *"It would put the FIRST non-write POST into a server
whose write-surface census... is a load-bearing safety artefact."* But `EP_TAILOR_JOBS`
(`endpoints.py:53`) is `"talent/hr/tailor-jobs" # POST JSON {HR_Number}` and it is declared
under the `--- Reads ---` header, and `uplers_tailored_jobs` calls
`client.post_json(endpoints.EP_TAILOR_JOBS, body)` at `server.py:2665`. A non-write POST was
already in the server on 2026-08-21, before the find-similar-job comment was written on
2026-08-22. Reasons 2 and 3 of that refusal are untouched by this and stand on their own; only
reason 1's premise is wrong. **Also worth noting: `uplers_tailored_jobs`'s own docstring calls
`talent/hr/tailor-jobs` "the 'jobs like this one' surface Uplers computes server-side" - which
is exactly what `find-similar-job` is, so reason 3 (near-zero payoff) is if anything
strengthened.** Recorded for you; I did not change the ruling.

**F4 - the README's tool counts are stale.** README line 14 says the public tier is "23 tools",
line 18 says the authenticated tier is "17 tools" (40 total), and line 838 says "all 22 public
tools work without it... and so do the other sixteen authenticated tools". MEASURED today:
**24 public and 23 authenticated, 47 total**, by AST enumeration and confirmed name-for-name
against the live MCP connection. Three different numbers appear in one file; none is current.
Section 1 of this census is the measured replacement.

**F5 - the README's "Deliberately out of scope" paragraph and its "namespace exception"
paragraph disagree on their face.** The out-of-scope paragraph names *"the rest of
`talent/outreach/*`"* as refused; the namespace-exception paragraph immediately above it admits
six reads under that prefix and states the current line (*"reads only"*). The exception
paragraph is the newer and operative one - `endpoints.py:98` says the same thing more sharply -
so I classified outreach READS as REACHABLE and outreach WRITES as REFUSED. **If that reading is
wrong, exactly 21 of the 37 REACHABLE-GAPs move to REFUSED and the count becomes 16** (the 21 are
G1, G2, G3, G6, G8, G9, G12-G23, G25, G34, G35 - every `talent/outreach/*` row; note
`talent/payment-transactions` at G7 is NOT under that prefix and survives either reading).
This is the single ruling the whole count is most sensitive to, which is why it is stated as a
number rather than left implicit.

### 7.1 Four BLOCKED rows that are one grep from REACHABLE

Each is a `GET/POST` pair where the inventory quoted only the POST body. One targeted read of
the named chunk resolves the GET's parameters and moves the row.

| row | route | chunks to read | what to extract |
|---|---|---|---|
| 74 | `talent/outreach/settings/followup` | 748, 8379, 9071 | the GET call site's URL - does it append anything? |
| 76 | `talent/outreach/settings/disabled-companies` | 748, 8379, 9071 | same |
| 45 | `talent/email-preference` | app.js (2 sites) | same |
| 104 | `talent/outreach/support` | 5422 and the 2 other sites | same |

Rows 74 and 76 are the two the brief called out by name ("the outreach agent's own
settings/config screens", "blocked-companies list"). Both are genuinely unresolved in the
evidence I was given; neither is refused. Resolving them would take the REACHABLE count from
37 to 41.

---

## 8. Appendix - routes that are NOT human-visible capabilities

Recorded so a later reader does not mistake them for gaps. A route with zero call sites is a
route no human reaches in a browser either, so it cannot be a parity gap.

**Defined but never handed to any HTTP helper (inventory A.1, 6):** the API base itself,
`images/talent/`, `images/login/`, `login` (a page URL), `talent/account/gmail/inbox/send`,
`talent/profile/delete-details`.

**Service wrapper never invoked - zero UI calls (inventory A.2, 10):**
`talent/account/analytics` (GET, no params, VERIFIED zero callers - the request shape is known
but no human ever triggers it), `feedback`, `otp-validity-check`, `otp-verify`, `profile/sso`,
`registration`, `sso`, `talent/store-password`, `talent/tailor/update`, `login`.

**Asset / helper routes, not capabilities:** `display-file`, `duplicate-talent-check`,
`talent/generate-upload-url`, `query`, `talent/set-password`, `coresignal/*`,
`store-talent-packet-feedback`, `talent/store-job-response`,
`new-signup/touchpoint-done-and-associate-in-hr`, `create-talent-ai-assessment`.

**Honest limit, carried from the inventory:** *"the wrapper is never invoked in this bundle" is
a complete negative search over 13.4 MB of shipped JS. It is NOT evidence the server route is
gone.* Everything in this appendix is "no human reaches it in this build", not "it does not
exist".

**One number in the inputs is known to over-count.** The inventory's UI-call column inflates
where a minified export key collides across webpack modules (`company-salary-feedback` shows 7,
has 1). The 2026-08-22 parity doc flags it: *"Treat that column as an upper bound."* No
classification in this census rests on that column - every one rests on the route, the method,
the quoted parameters, or a measured fixture.
