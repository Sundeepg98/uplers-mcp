"""Route constants and enums for the authenticated talent API.

Every constant here was extracted from Uplers' own production React bundle
(`/build/apptalent/js/app.js` plus its 85 lazy chunks, 13.4 MB total) on
2026-08-21 and cross-checked against a live unauthenticated probe. The full
evidence, with verbatim call-site excerpts, is in
`mcp-servers/_audit/2026-08-21-uplers-bundle-callsites.md`.

Three facts drive everything downstream, and all three CORRECT the earlier
route-map research in `tools/uplers-api-research.md`:

1.  **Auth is a bearer token, not a cookie session.** Every call site does
    ``Authorization: Bearer <localStorage["token"] ?? localStorage["guest_token"]>``.
    The `uplers_session` cookie exists but the SPA never relies on it, and
    `X-XSRF-TOKEN` is never attached by application code - the only occurrences
    in the bundle are inside axios's own bundled default config.

2.  **The logged-out signal is a 401, not a 302.** MEASURED live: with
    ``Accept: application/json`` every ``talent/*`` route answers
    ``401 {"message":"Unauthenticated."}``; without it Laravel's
    `Authenticate` middleware redirects to `/console/login` with an HTML body.
    Since this client always asks for JSON, 401 is the normal signal - but the
    302 is still handled, because a middleware change should not read as
    "logged in".

3.  **`hr_id` names two different identifier spaces.** See IDENTIFIER_SPACES.
    Sending the wrong one is a silent no-op or a 422, not an obvious error.
"""

from __future__ import annotations

from . import config

# Absolute base for every authenticated call. The SPA sets no axios baseURL and
# builds absolute URLs by string concatenation, so this mirrors it exactly.
API_BASE = config.BASE_URL + "/api/"

# Where an unauthenticated browser-shaped request gets redirected. Seeing this
# in a Location header means "not logged in", never "moved".
LOGIN_REDIRECT = config.BASE_URL + "/console/login"

# The page a human signs in on. NOT the same as LOGIN_REDIRECT: the API
# redirects unauthenticated browser-shaped requests to /console/login, but the
# talent-facing sign-in page is /login, and it is the one carrying Google SSO.
# Conflating the two opened the wrong page and the operator could not sign in.
LOGIN_URL = config.BASE_URL + "/login"

# --- Reads ----------------------------------------------------------------

EP_OPPORTUNITIES = "talent/hr/opportunities"          # GET, query string
EP_MY_OPPORTUNITIES = "talent/hr/my-opportunities"    # GET, query string
EP_SINGLE_HR = "talent/hr/single-hr"                  # GET, ?hr_number=
EP_TAILOR_JOBS = "talent/hr/tailor-jobs"              # POST JSON {HR_Number}
EP_PROFILE = "talent/profile"                         # GET (POST upserts)
EP_ACCOUNT_STATUS = "talent/account/status"           # GET, no params

#: HIS assessment record - which tests he has sat, and how they went.
#:
#: The catalogue half of this is already built: every public record carries an
#: `assessments` array and `Opportunity.assessments_required` counts it. That
#: says what a REQUISITION demands. This route says what HE has done, and the
#: two together decide whether a required assessment is an obstacle or an
#: afternoon already spent. 99 of the 250 records in the index carry a
#: non-empty assessments array, so this is not a rare edge.
#:
#: VERIFIED in the bundle as export `TU`, a GET with no params whose service
#: resolves `res.data.data` DIRECTLY rather than the axios response:
#: ``(0,i.Yr)(o.TU).then(function(e){t(e.data.data)})``. Note the ``v2/``
#: prefix - it is the only versioned route on this API surface.
EP_ASSESSMENTS = "v2/assessments"                     # GET, no params

EP_ROLE_MASTER = "talent/hr/all-opp-role-master"
EP_SKILL_MASTER = "talent/hr/all-opp-skill-master"
EP_LOCATION_MASTER = "talent/hr/all-opp-location-master"
EP_COMPANY_MASTER = "talent/hr/all-opp-company-master"

#: Read-only list of the operator's own interviews.
#:
#: NAMESPACE NOTE, deliberate and flagged: this sits under ``talent/outreach/``,
#: which is otherwise excluded from this server because that prefix is where
#: Uplers' paid outreach-agent product lives. This one route is a plain GET of
#: the operator's OWN interview schedule - reading your own calendar is using
#: the platform normally, not reimplementing a SKU. The write half of the pair
#: (``talent/outreach/interview-feedback``) is deliberately NOT built.
EP_INTERVIEW_LIST = "talent/outreach/interview-list"  # GET, ?detailed=true

#: HIS OWN AGENT'S OUTPUT. Five plain GETs, all VERIFIED LIVE on 2026-08-23 by
#: `scripts/capture_outreach.py`, whose responses are committed as fixtures.
#:
#: NAMESPACE NOTE, the same one EP_INTERVIEW_LIST carries and for the same
#: reason. `talent/outreach/*` is where Uplers' PAID outreach-agent product
#: lives and this server excludes it - but he is PAYING for that agent right
#: now (`plan: 2`, `auto_run: 1`, `outreach_mode: "auto"`, through 2026-09-10)
#: and its entire output was invisible here. Reading what an agent you already
#: own has done is using the platform normally; it is not reimplementing the
#: SKU. Precedent already on record: EP_INTERVIEW_LIST.
#:
#: THE LINE IS READS ONLY, and it is a hard one. The write half of this
#: namespace stays unbuilt: `interview-feedback`, `consent-email-job-scan`,
#: and anything that would make a SECOND agent apply from one account. He
#: already has an applier; a second uncoordinated one against a
#: 250-requisition board where apply is permanent is the wrong answer.
#:
#: ENVELOPE TRAP, measured rather than assumed: these five do NOT share one
#: success idiom. `outreach-step` answers `{"status": "success", ...}` - the
#: STRING - while the other four answer `{"status": 200, ...}` - the INTEGER.
#: `outreach.unwrap` accepts both and refuses anything else.
EP_OUTREACH_STEP = "talent/outreach/outreach-step"
EP_OUTREACH_DASHBOARD = "talent/outreach/get-outreach-dashboard-data"
EP_OUTREACH_PENDING = "talent/outreach/pending-jobs"
EP_OUTREACH_MISSED_FOLLOWUPS = "talent/outreach/missed-positive-reply-followups"
EP_OUTREACH_ACTIVITY = "talent/outreach/agent-tailor-activity"

#: THE NEXT RING OF THE SAME NAMESPACE, and the same hard line: READS ONLY.
#: All six VERIFIED LIVE 2026-08-23 and captured as fixtures by
#: `scripts/capture_agent_surface.py`; every one answered a real 200 with real
#: data on his live session, and each fixture is named beside its route below.
#:
#: THE ENVELOPE TRAP BITES AGAIN, and differently than the five above did.
#: `get-message-templates` answers `{"status": "success"}` - the STRING - while
#: the other five answer the INTEGER 200, so the split does NOT run along
#: "old routes vs new routes" or along any other line a reader could guess.
#: `outreach.unwrap` already accepts exactly those two idioms and refuses
#: everything else, which is why nothing here grows a second unwrapper.

#: The AUTHORITATIVE Gmail-job-scan consent, and the reason this ring exists.
#: Established by static analysis of Uplers' own bundle
#: (`_audit/_slices/_slice-consent-semantics.md`, chunk 3474): this is the route
#: the UI RE-READS immediately after the consent write lands, and its
#: `has_consent` is what the whole Recommended-jobs screen switches on.
#: `get-outreach-dashboard-data -> consent_email_job_scan` is a downstream copy,
#: and `EP_INTERVIEW_LIST -> meta.has_consent` is a DIFFERENT consent entirely
#: (the interview scan, whose UI Uplers designed but never shipped) despite the
#: identical field name.
EP_OUTREACH_META_EMAIL = "talent/outreach/recommended-jobs-meta-email"

#: The jobs that scan actually found. Takes `best_for_you`; MEASURED 2026-08-23
#: as unset -> 79 rows and `true` -> 51. It has no working `limit`: a `limit=3`
#: on its sibling `get-recommended-jobs` returned all 97 rows, so any
#: truncation of this route is the CALLER's, never the server's.
EP_OUTREACH_SCANNED_JOBS = "talent/outreach/recommended-jobs-email"

#: Whether an unanswered reply gets chased at all, per channel. Its
#: `disabled_followup_*` flags are INVERTED - false means the channel is ON.
EP_OUTREACH_SETTINGS_FOLLOWUP = "talent/outreach/settings/followup"

#: The real blocklist, 16 rows on 2026-08-23, and what Uplers means when an
#: agent run fails with "You blocked this company for outreach".
#:
#: NOT `talent/outreach/settings/companies`. That one is the alphabetical
#: company PICKER, paginated at 20, where `IsActive` marks a chosen row - a
#: different list with a confusingly similar path. Reading the blocklist off it
#: would report the first 20 companies in the alphabet as blocked. It is
#: captured as `tests/fixtures/outreach_settings_companies.json` and
#: deliberately has no constant here, because a name is an invitation to call
#: it and no tool in this server should.
EP_OUTREACH_DISABLED_COMPANIES = "talent/outreach/settings/disabled-companies"

#: The auto-reply switch, its delay, and the 8 categories it can answer.
#: MEASURED `handle_auto_reply: false` - the feature exists and is off.
EP_OUTREACH_AUTO_REPLY = "talent/outreach/get-auto-reply"

#: The outreach message templates. The one route in this ring whose body is
#: PERSONAL: `gmail_template` is a multi-paragraph self-description carrying
#: employer history, a LinkedIn URL and a notice period. Whatever reads this
#: reports that a template EXISTS and what its SUBJECT is, never the body.
EP_OUTREACH_TEMPLATES = "talent/outreach/get-message-templates"

#: THE ONLY ROUTE THAT COUNTS THE REPLIES THAT SAID NO. Everything else in
#: this ring counts positives: the dashboard reports `total_positive_replies`
#: and `total_unseen_replies`, `missed-positive-reply-followups` returns the
#: positive threads by name. So "8 positive replies" read as the whole story of
#: what came back, and it was not - MEASURED LIVE 2026-08-23:
#: ``{total_positive_replies: 8, total_negative_replies: 2}``. Ten people
#: answered, not eight.
#:
#: It is also a genuine CROSS-CHECK rather than just an addition: it reports
#: `total_positive_replies` on a different route from the dashboard, so the two
#: can be held against each other. They agreed on capture, which is a fact
#: worth having rather than an assumption worth making.
EP_OUTREACH_AGENT_META = "talent/outreach/get-outreach-agent-meta"

#: What UPLERS thinks he wants, which is not what this server's profile says.
#: Fit scores here come from our own profile; Uplers ranks him against these.
#: Seeing both is how a disagreement between the two becomes visible at all.
#:
#: VERIFIED LIVE 2026-08-23 (a real 200 with real data, not a bundle constant).
#: Recorded because a prior slice confused two constants: `fJ7` is the
#: NURTURE-preference route, NOT this one. Nothing here touches nurture.
#:
#: Its sibling `user/job-search-preference` is a real WRITE that changes how he
#: appears to recruiters. Not built, and not to be confused with this.
EP_GET_PREFERENCE = "talent/get-preference"                  # GET, no params

# --- Read query parameters ------------------------------------------------

#: The SERVER-SIDE saved-jobs view. `uplers_save_job` is a LOCAL shortlist and
#: says so; this is Uplers' own bookmark, and the two are disjoint today.
#:
#: BUILT, and it lives BELOW this line rather than under "recorded, deliberately
#: NOT built" because it is called: `uplers_platform_saved_jobs` sends it, via
#: `saved_filter.saved_jobs_params()`, which is the only builder allowed to
#: construct this query. It sat under the not-built banner - the one that reads
#: "No tool calls any of these" - until 2026-08-24, which made that banner false
#: for the whole section it governs.
#:
#: TWO CONTRACT DETAILS THAT PRODUCE A SILENTLY WRONG RESULT RATHER THAN AN
#: ERROR, both VERIFIED in chunk 8562 (the builder the LIVE jobs board uses -
#: NOT chunk 2893, which the 2026-08-21 audit read and which never emits this):
#:
#:   1. it is sent as the integer ``1``, never ``true``;
#:   2. it is **EXCLUSIVE** - `1===t.is_saved_filter` short-circuits the
#:      `Object.keys(t).map(...)` branch, so `roles`, `locations`, `experience`,
#:      `engagements` and the rest are all DROPPED. Only `search` may ride
#:      alongside it; `pagination`, `page`, `is_count` and `activeJob` sit
#:      outside the ternary and are always sent.
#:
#: Sending it with filters would therefore return his saved jobs UNFILTERED
#: while the caller believed the filters applied. Both facts are now PINNED
#: rather than merely recorded: `saved_filter.assert_integer_one` rejects the
#: bool and the string `"1"`, the module refuses any filter outside
#: COMPATIBLE_FILTERS, and `tests/test_saved_filter.py` carries the controls -
#: including one proving `json.dumps` renders `True` as `true`, which is the
#: exact wire shape detail 1 forbids.
#:
#: The in-house board (chunk 2646) does the same, minus `search`, and adds
#: `&type=inhouse`.
QP_IS_SAVED_FILTER = "is_saved_filter"                # GET EP_OPPORTUNITIES, value 1

# The route used to prove a session is real. Chosen because its 401-when-logged-out
# behaviour was MEASURED live on 2026-08-21, not assumed.
EP_AUTH_PROBE = EP_PROFILE
AUTH_PROBE_NOTE = 'GET /api/talent/profile (401 {"message":"Unauthenticated."} when logged out)'

# --- Writes ---------------------------------------------------------------
# BUILT: EP_INTRESTED (uplers_apply), EP_NOT_INTERESTED (uplers_dismiss) and
# EP_PROFILE_UPSERT (uplers_update_profile / uplers_restore_profile and
# uplers_replace_resume / uplers_restore_resume).
# RECORDED ONLY, no caller anywhere in this server: EP_CANCEL_OPPORTUNITY and
# EP_UPDATE_SAVED_HR.
#
# The header here read "shapes recorded; only job-not-interested is built"
# until 2026-08-24. It was written when that was true and was never revisited
# as the other two landed, so it under-reported the write surface by two
# routes - in the one file whose job is to say what this server can reach.

EP_INTRESTED = "talent/hr/intrested"                  # POST multipart - THIS IS APPLY
EP_NOT_INTERESTED = "talent/hr/job-not-interested"    # POST JSON, reversible

#: THE ONLY ROUTE IN THIS SERVER THAT CHANGES WHO HE IS. Everything else writes
#: to a requisition; this writes to him.
#:
#: TWO USERS, not one, and they send DIFFERENT BODIES down the same route:
#:
#:   * `field="skills"` - a POST of JSON, the skills write described below.
#:     `uplers_update_profile` / `uplers_restore_profile`.
#:   * `field="resume"` - a POST of MULTIPART carrying raw file bytes as
#:     `value`. `uplers_replace_resume` / `uplers_restore_resume`, orchestrated
#:     by `uplers_server.resume_write`, which is handed this constant by
#:     `server.py` and never names it itself. Its shape and the reason it is a
#:     one-way door on Uplers' side are in that module's docstring.
#:
#: The second user landed after this comment was written and the comment went
#: on describing only the first until 2026-08-24. Both are replacements; only
#: the skills half is described in detail below.
#:
#: **REPLACEMENT SEMANTICS - an omitted skill is DELETED.** Body is
#: ``{"field": "skills", "value": [<EVERY skill>], "tid"?}`` and the response
#: `res.data.data` is the saved ARRAY.
#:
#: This is a DIFFERENT route from `talent/profile`, and the difference is the
#: dangerous part. `talent/profile` POST carries a section-keyed SINGULAR
#: envelope (`{experience: {...}}`, `{achievmentsNew: {...}}`) - a per-entity
#: upsert, paired with `talent/profile/delete-details` for removal. This one
#: carries `{field, value}` and replaces the whole field. Confusing the two
#: means sending one skill to a route that treats it as the complete list.
#:
#: VERIFIED: chunk 196 module 30196 @122419, resolved through app.js module
#: 26878 (`P7`) to module 81935 (`Imf`). The proof that removal is an omission
#: rather than a delete call is their own remove handler at @126363, which
#: splices the local array and issues no request. Skills is also the only
#: profile section with NO delete route - all six siblings have one. Full
#: evidence: `_audit/2026-08-21-uplers-skills-write-shape.md`.
EP_PROFILE_UPSERT = "talent/profile-upsert"           # POST JSON {field, value}
EP_CANCEL_OPPORTUNITY = "talent/hr/cancel-opportunity"  # POST JSON, dead code in this build
EP_UPDATE_SAVED_HR = "talent/hr/update-saved-hr"      # POST JSON {hr_id: enc_id, type}

# --- Recorded, deliberately NOT built -------------------------------------
# Shapes kept here so the findings are not lost. No tool calls any of these.
# Recorded 2026-08-22 from the exhaustive route sweep
# (`_audit/_slices/_slice-uplers-route-inventory.md`, 214 API paths) and its
# shape follow-up.

#: Per-JOB estimated salary and company detail. Both `?hr_id=`, both answering
#: `res.data.status == 200` with `salary_data` / `company_data`.
#:
#: The salary service has a dedicated **403 branch** that resolves
#: ``{data:{salary_data:null}}`` - a client that EXPECTS to be refused, which is
#: strong evidence the surface is an account entitlement rather than open data.
#:
#: WHAT IS NOT ESTABLISHED, recorded so nobody repeats the probes: on 2026-08-22
#: six live GETs (HR_Number / numeric id / enc_id, against one closed and one
#: open requisition) every one answered ``{"status":400,"errors":"No HR found.."}``.
#: **No 403 was ever observed, so the entitlement question is UNTESTED, not
#: answered** - what is unknown is which identifier space `hr_id` names here. It
#: is not any of the three this API uses elsewhere. The remaining hypothesis is
#: that the estimated-salary pill exists only on AGGREGATED postings, which this
#: server deliberately does not fetch, so it was not testable from here.
EP_COMPANY_SALARY = "get-company-salary-data"         # GET ?hr_id= (id space UNRESOLVED)
EP_COMPANY_DETAIL = "get-company-detail"              # GET ?hr_id= (id space UNRESOLVED)

#: "Jobs like this one." RECORDED, DELIBERATELY NOT BUILT, and the first
#: reason is a correction: it was handed to this wave as a read. It is not.
#:
#: It is a **POST**, body ``{hr_id, user_email}``, VERIFIED in app.js as export
#: `NuB` (`_slice-uplers-route-inventory.md`, four UI call sites). `hr_id` here
#: is the HR NUMBER off the pathname - neither `enc_id` nor the numeric id, which
#: is a third spelling of the same argument on the same API. Response is
#: `res.data.data` and it is a list.
#:
#: Read-SHAPED, since the bundle only ever spreads the result into redux, but
#: read-shaped is not read. TWO reasons it stays unbuilt, and both are about
#: this route rather than about POSTs in general:
#:
#:   1. It sends HIS EMAIL ADDRESS in the body to get back a list.
#:   2. The payoff is near zero here. This server already indexes all 250
#:      requisitions locally, so "similar to this one" is answerable offline by
#:      `uplers_rank_opportunities()` against a record we already hold - with
#:      jobcore's scoring, which is comparable across servers, rather than
#:      Uplers' opaque one.
#:
#: A THIRD REASON WAS WITHDRAWN ON 2026-08-24 BECAUSE IT WAS FALSE. It read:
#: building this "would put the FIRST non-write POST into a server whose
#: write-surface census is a load-bearing safety artefact". It would not. That
#: POST already exists and predates the claim: `EP_TAILOR_JOBS` sits under
#: "Reads" above, is documented there as `POST JSON {HR_Number}`, and
#: `uplers_tailored_jobs` reaches it through `post_json`. The census that
#: matters counts writes by EFFECT - what changes on Uplers - and never by HTTP
#: verb, which is why a read-shaped POST has always been countable as a read
#: and why `tailor-jobs` never inflated it. The withdrawn reason is recorded
#: rather than deleted so a later session does not re-derive it from the same
#: mistaken premise. The refusal stands on the two reasons above; it is worth
#: more resting on two true ones than on three with a false one among them.
#:
#: Not probed live either: a POST to an unbuilt route on his live account, for
#: a feature already decided against, is a spend with no payoff.
EP_FIND_SIMILAR_JOB = "find-similar-job"          # POST {hr_id: HR_Number, user_email}
EP_TALENT_MATCHMAKE = "talent-matchmake"          # POST {hr_id: HR_Number}, same page

#: Why `uplers_my_interviews` can return an empty diary that is NOT "no
#: interviews": Uplers builds that list by scanning a connected mailbox, and
#: MEASURED 2026-08-22 his `meta` read
#: ``{has_consent: false, consent_interview_email_scan: null, gmail_connected: true}``.
#: A mailbox is connected; the scan was never consented to. This is the route
#: that flips it - and it is a WRITE, in the excluded `talent/outreach/*`
#: namespace, that changes what Uplers reads on his behalf. His call, not this
#: server's.
EP_CONSENT_EMAIL_JOB_SCAN = "talent/outreach/consent-email-job-scan"  # POST/DELETE

# --- Measured unreachable -------------------------------------------------
# A DIFFERENT CLASS from the block above. Everything above this line is a route
# that WORKS and is deliberately not called. These two were CALLED and did not
# answer, so no decision is being recorded here - a measurement is.

#: MEASURED **HTTP 404** on 2026-08-23, on a LIVE session, with a real
#: `outreach_hr_id` taken off an `agent-tailor-activity` row - the same id that
#: answered 200 on every other route in that ring. Both had been listed as
#: buildable GET reads by the browser-parity census, off the bundle inventory;
#: a path that appears in the bundle is not a path the API serves.
#:
#: THE OPEN QUESTION IS THE PARAMETER SPACE, NOT THE SESSION. The session was
#: good and the id was good, so "re-probe after logging in" is not the retry
#: that could change this answer; finding the identifier or query these two
#: actually want is. They are not retried here.
#:
#: The measurement is executable at `scripts/capture_agent_surface.py`, whose
#: `MEASURED_404` tuple carries the same two paths and keeps them out of the
#: capture set. Written down twice on purpose: the script is where the probe
#: lives, this file is where a reader looks for what a route does.
MEASURED_404 = (
    "talent/outreach/outreached-people",      # ?outreach_hr_id= -> 404
    "talent/outreach/get-employee-requests",  # ?outreach_hr_id= -> 404
)

# --- Enums, verbatim from bundle module 22000 -----------------------------

SORT_FIELDS = ("relevance", "created_at")

#: Experience filter values are "min,max" RANGE STRINGS, not numbers.
EXPERIENCE_BANDS = (
    "0,2", "2,4", "4,6", "6,8", "8,10", "10,12", "12,14",
)

#: `engagements` is a JSON-encoded array of objects: [{"type": "Remote"}].
ENGAGEMENT_MODES = ("Onsite", "Hybrid", "Remote")

#: The only `company_type` value appearing anywhere in 13.4 MB of bundle.
DEFAULT_COMPANY_TYPE = "maang"

# --- Identifier spaces ----------------------------------------------------

#: Three identifiers name the same requisition, and the API is not consistent
#: about which it wants. Getting this wrong is the most likely silent bug in
#: any client of this API, so it is written down rather than remembered.
IDENTIFIER_SPACES = {
    "id": "Plain numeric id. Sent as `hr_id` by intrested and cancel-opportunity.",
    "enc_id": "Encrypted id. Sent as `hr_id` by update-saved-hr and assign-assessment.",
    "HR_Number": (
        "The public 'HR...' string. Used by single-hr (?hr_number=), "
        "my-opportunities (activeJob=), job-not-interested (hr_number) and "
        "everything in this server's public tier."
    ),
}

# --- Response envelopes ---------------------------------------------------

#: Laravel paginator routes: rows live at res["hrs"]["data"].
PAGINATED_ROUTES = (EP_OPPORTUNITIES, EP_MY_OPPORTUNITIES)

#: Uplers uses BOTH a string and a numeric success flag, on different routes.
#: update-saved-hr checks `status === "success"`; recommendations checks
#: `status === 1`. Never write one check for both.
SUCCESS_STRING = "success"
SUCCESS_NUMERIC = 1
