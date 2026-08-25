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
#: the platform normally, not reimplementing a SKU.
#:
#: CORRECTED 2026-08-25: this comment used to end "The write half of the pair
#: (``talent/outreach/interview-feedback``) is deliberately NOT built." That is
#: no longer true - see :data:`EP_INTERVIEW_FEEDBACK` directly below, which is
#: now built behind ``uplers_server.consent_write``. The sentence is replaced
#: rather than deleted, because a reader who remembers the old refusal needs to
#: find out that it was lifted, not to find silence where it stood.
EP_INTERVIEW_LIST = "talent/outreach/interview-list"  # GET, ?detailed=true

#: THE WRITE HALF OF THAT PAIR, and the FIRST genuinely ONE-WAY route this
#: server calls anywhere in ``talent/outreach/*``. Added 2026-08-25.
#:
#: **ONE-WAY, VERIFIED BY A COMPLETE NEGATIVE SEARCH: no edit route and no
#: delete route for submitted feedback exists anywhere in Uplers' bundle.** The
#: only thing that can follow it is a repeat POST for the same ``company_id``,
#: and whether their server overwrites or appends is NOT decidable from the
#: client - it patches its own row either way
#: (``_slice-outreach-write-inventory.md`` section 9, item 5).
#:
#: Body: ``{company_id, feedback}`` - EXACTLY TWO KEYS, VERIFIED at all four
#: call sites across three screens (1625, 2063, 6069):
#: ``(0,i.o$)(...+"talent/outreach/interview-feedback",{company_id:t,feedback:n})``.
#: Response read as ``res.data.status === "success"``, with validation errors at
#: ``res.data.errors.feedback[0]``. Evidence: section 3.19 of the same slice.
#:
#: THIS BREAKS THE RULE THE ONE-WAY BLOCK BELOW STATES, AND DOES IT ON PURPOSE.
#: That block records the remaining one-way routes as PROSE rather than
#: constants, on the ground that "a constant is an invitation to call it". Nine
#: of them still are. This one has a constant because it is CALLED, and a route
#: this server calls with no constant would be a path string living in
#: server.py where nothing could census it. The invitation argument is answered
#: by the guards rather than by the absence of a name: the write refuses
#: without a sender, refuses without ``confirm=True``, and refuses outright
#: unless the company is on the live interview list - which is currently EMPTY,
#: so it refuses every call today.
EP_INTERVIEW_FEEDBACK = "talent/outreach/interview-feedback"  # POST {company_id, feedback}

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
#: THE LINE WAS READS ONLY UNTIL 2026-08-24, and it moved by exactly four
#: routes - all four REVERSIBLE SETTINGS writes, none of them a send. Each one
#: is marked WRITE ARM and sits directly under the read it pairs with, in the
#: ring below.
#:
#: IT MOVED AGAIN ON 2026-08-25, by exactly two more routes, and this note is
#: edited rather than left standing because it used to name both of them as
#: unbuilt. `interview-feedback` and the DELETE arm of `consent-email-job-scan`
#: are now built behind `uplers_server.consent_write`, censused in their OWN
#: group (`server.CONSENT_AND_ONE_WAY_WRITE_TOOLS`) rather than folded in with
#: the four above - because those four are grouped by "can be put back" and one
#: of these two cannot.
#:
#: WHAT STILL HAS NOT MOVED is the part that mattered: `store-employee-requests`
#: (the actual outreach send, whose own UI copy says it cannot be undone), the
#: GRANT arm of the consent, `consent-auto-run`, and anything that would make a
#: SECOND agent apply from one account stay unbuilt. He already has an applier;
#: a second uncoordinated one against a 250-requisition board where apply is
#: permanent is the wrong answer.
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

#: THE NEXT RING OF THE SAME NAMESPACE. Six READS, and - since 2026-08-24 -
#: the four REVERSIBLE WRITE arms that sit on four of them. Each write arm is
#: marked WRITE ARM and sits directly under its read; anything in this ring
#: without that marker is a plain GET.
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
#:
#: WRITE ARM: **THE SAME PATH STRING, POSTed.** There is no second constant for
#: it and there must not be - a second spelling of one path is a second thing
#: to keep in step. VERIFIED at chunk `748` @15521 (twin `9071`), the only POST
#: call site in 13.4 MB of bundle: a flat 9-key object literal, no spread,
#: every key sent every time, `channel` the hardcoded literal `"both"`, and
#: each `interval_days*` clamped client-side by `e > 0 ? e : 1`. The GET arm at
#: `748` @10953 falls back from `disabled_followup_gmail`/`_linkedin` to a
#: legacy singular `disabled_followup` and from `interval_days_gmail`/`_linkedin`
#: to `interval_days`; **the POST never sends the singular flag** - there is no
#: `disabled_followup` key in the body. Two client-side gates run before it: a
#: channel's message must contain BOTH `{{outreachEmployee}}` and `{{jobTitle}}`
#: unless that channel is disabled or its message is empty. All of it is
#: mirrored in `uplers_server.outreach_write`, which is handed a sender by
#: server.py and cannot reach this route on its own.
#: Evidence: `_audit/_slices/_slice-outreach-write-inventory.md` section 6.
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

#: WRITE ARM, ADD: **the same path string, POSTed**, body `{company_id}`, and
#: like the follow-up route it gets no second constant. VERIFIED chunk `748`
#: @13095; the response's `res.data.data` is the created blocklist row.
#:
#: WRITE ARM, REMOVE: a DELETE whose id is a **PATH SEGMENT**, no body and no
#: params. VERIFIED chunk `748` @13890. This one DOES get its own constant
#: because the path is genuinely different, and it is a TEMPLATE rather than a
#: prefix on purpose: a caller that concatenated onto the bare collection path
#: and got the id wrong would issue `DELETE` at the COLLECTION URL. The `{id}`
#: placeholder makes that impossible to do by accident, and
#: `outreach_write.delete_sender_for` refuses any path that does not carry it.
#:
#: **THE ID IS THE BLOCKLIST ROW'S `id`, NOT `company_id`.** The two live side
#: by side on every row (`{"id": 261, "company_id": 19868, ...}` in
#: `tests/fixtures/outreach_disabled_companies.json`), both are small integers,
#: and swapping them unblocks a different company or nothing at all - silently,
#: with a 200. VERIFIED from their own local filter after the DELETE succeeds:
#: `e.filter(function(e){return e.id!==n})`, where `n` is the path segment. The
#: POST's `{company_id}` comes from the OTHER space. This is the same class of
#: trap as IDENTIFIER_SPACES below, on one route, one path apart.
EP_OUTREACH_DISABLED_COMPANY_DELETE = (
    "talent/outreach/settings/disabled-companies/{id}"
)

#: The auto-reply switch, its delay, and the 8 categories it can answer.
#: MEASURED `handle_auto_reply: false` - the feature exists and is off.
EP_OUTREACH_AUTO_REPLY = "talent/outreach/get-auto-reply"

#: WRITE ARM of the route above, and the one write arm in this ring whose path
#: is NOT its read's: the read is `get-auto-reply`, the write is
#: `update-auto-reply`. Body `{hours, handle_auto_reply, auto_reply_categories}`,
#: all three always sent. VERIFIED chunk `8379` @73141 (second call site
#: `app.js` @5391603). One client-side gate runs before it: enabling with an
#: empty `auto_reply_categories` is refused ("Select at least one category to
#: enable auto-reply"). Mirrored in `uplers_server.outreach_write`.
EP_OUTREACH_UPDATE_AUTO_REPLY = "talent/outreach/update-auto-reply"

#: The outreach message templates. The one route in this ring whose body is
#: PERSONAL: `gmail_template` is a multi-paragraph self-description carrying
#: employer history, a LinkedIn URL and a notice period. Whatever reads this
#: reports that a template EXISTS and what its SUBJECT is, never the body.
EP_OUTREACH_TEMPLATES = "talent/outreach/get-message-templates"

#: WRITE ARM of the route above, and the second one whose path is not its
#: read's. Body `{message_template, message_subject, provider}` - exactly three
#: keys, **no `tag`** - and ONE CHANNEL PER CALL. VERIFIED at all 6 call sites
#: of the template editor (`_slice-outreach-write-inventory.md` section 5, Path
#: B). Path A, the preview screen, sends a fourth key `tag` and is deliberately
#: not built.
#:
#: **`provider` IS A NUMBER: 1 = LinkedIn, 2 = Gmail.** VERIFIED three ways -
#: the declaration `oe=1,ie=2`, the demux `c===ie?r.gmail_message_id=u:...`,
#: and an independent call site carrying the literal `provider:2` for a gmail
#: save. The string `"gmail"` here is a different call, not a synonym.
#:
#: **THERE IS NO DELETE-TEMPLATE ROUTE ANYWHERE IN THE BUNDLE**, so this write
#: is recoverable only from a copy taken BEFORE it. That is what
#: `outreach_write.write_snapshot` is for, and why it is the one snapshot in
#: this ring that has to hold personal text.
EP_OUTREACH_STORE_TEMPLATE = "talent/outreach/store-message-template"

# --- Same namespace, ONE-WAY, deliberately NOT built ----------------------
# Recorded as PROSE and not as constants, on purpose: a constant is an
# invitation to call it, and every route named here changes something on
# Uplers that nothing can change back. The four writes above are in this
# server BECAUSE they are reversible; these are out for the opposite reason.
#
# NINE, NOT TEN, SINCE 2026-08-25. `interview-feedback` was the tenth and it
# is now BUILT, with a constant of its own (EP_INTERVIEW_FEEDBACK, above) -
# so this list is one shorter and the rule it states now has one deliberate
# exception rather than none. The exception is argued at that constant: a
# route the server actually calls needs a name something can census, and the
# "invitation" is answered by the guards around the call. Nothing else moved:
# the nine below are still refused, still nameless, and still one-way.
# Shapes and evidence live in `_audit/_slices/_slice-outreach-write-inventory.md`
# (section 1a), which is where to look if one of them ever has to be built.
#
#   talent/outreach/store-employee-requests   THE ACTUAL OUTREACH SEND. Uplers'
#                                             own UI copy says it cannot be
#                                             undone. This is the SKU.
#   talent/outreach/reveal-email              spends a reveal, one way
#   talent/outreach/discard-job               drops a job out of the agent's
#                                             queue with a feedback reason
#   talent/outreach/auto-run-request          starts an agent run
#   talent/outreach/extend-free-trial         )
#   talent/outreach/claim-discount-offer      )  the five commercial claim
#   talent/outreach/claim-custom-light-plan   )  routes - each one spends or
#   talent/outreach/claim-referral-code       )  consumes an entitlement that
#   talent/outreach/verify-referral-code      )  cannot be un-spent


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

#: THE PAID-SKU READS. Three GETs, no params, all VERIFIED LIVE 2026-08-25 -
#: a real 200 with real data on his own session, zero 403s and zero 402s -
#: and captured as fixtures by `scripts/capture_skus.py`.
#:
#: THEY OVERTURN HALF OF A STANDING REFUSAL, and the half they leave standing
#: matters as much as the half they remove. `out_of_scope_by_design` refused
#: `talent/resume-health-check/*` and `talent/tailor/*` wholesale as paid
#: candidate products, reasoning that wrapping them "would produce tools that
#: fail at runtime" because the account holds zero tailor credits. MEASURED:
#: that is true of the ORDERING routes and false of these three READS. A credit
#: balance gates buying a tailored resume; it does not gate reading the health
#: check he has already had or the plan he already holds. Every ordering,
#: transforming and refunding route in both namespaces stays refused and stays
#: nameless here, on the rule this file already applies to the one-way outreach
#: routes above: a constant is an invitation to call it.
#:
#: ALL THREE ANSWER THE INTEGER 200, none of them the string `"success"`.
#: MEASURED per route rather than inferred - which is the whole reason
#: `outreach.unwrap` takes both idioms and refuses everything else.
#:
#: THE HEALTH-CHECK ROUTE IS THE MOST PERSONAL PAYLOAD THIS SERVER READS. Its
#: `report_details` node is Uplers' scoring report on his resume: his name, his
#: city, and whole bullets of the resume quoted back verbatim. `uplers_server.
#: skus` does not return it and `capture_skus.py` does not keep it - see
#: `SKU_DROP` in `scripts/capture_outreach.py`.
#:
#: NAMESPACE NOTE: the first of the three sits under `talent/outreach/` despite
#: having nothing to do with outreach, one path segment from
#: `consent-email-job-scan`. The other two are the only routes in this file
#: under their own prefixes.
EP_SKU_HEALTH_CHECK_LAST = "talent/outreach/get-last-health-check"
EP_SKU_HEALTH_CHECK_DASHBOARD = "talent/resume-health-check/dashboard"
EP_SKU_TAILOR_LIST = "talent/tailor/list"

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
# NOT THE WHOLE WRITE SURFACE, and this line exists so nobody reads it as one.
# Four more writes live UP THIS FILE, beside their reads in the outreach ring,
# each marked WRITE ARM: the follow-up settings POST and the disabled-companies
# POST (both on the same path string as their GET, so neither has a constant of
# its own), EP_OUTREACH_DISABLED_COMPANY_DELETE, EP_OUTREACH_UPDATE_AUTO_REPLY
# and EP_OUTREACH_STORE_TEMPLATE. Their guards are in
# `uplers_server/outreach_write.py`, which is handed a sender by server.py and
# names none of the three write-only constants itself. It DOES name the four
# read constants - it has to, to read the record back - and for the follow-up
# and disabled-companies POSTs that read constant is also the write path,
# because Uplers reused one path across two verbs. What stays structural there
# is the sender, not the string: no route constant this module holds can put
# anything on the wire.
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
#: RESOLVED 2026-08-24, and both halves of the old note were wrong.
#:
#: `hr_id` IS THE ROW'S PLAIN NUMERIC `id`. VERIFIED in the bundle, where the
#: value is PRODUCED rather than consumed - the estimated-salary-pill component
#: (module 25397) reads ``f = hrData.id`` and sends ``"?hr_id=".concat(f)``.
#: Proven live by a one-row control: the SAME requisition answers 200 with its
#: `id` and 400 ``{"errors":"No HR found.."}`` with its `HR_Number`.
#:
#: AND IT IS NOT AN ENTITLEMENT. Every live probe answered 200; not one answered
#: 403. The dedicated 403 branch is real but this account is never refused, so
#: the earlier reading of it as "strong evidence of an account entitlement" was
#: an inference the measurement did not support.
#:
#: THE SIX 400s WERE THE WRONG ROWS, NOT THE WRONG ID SPACE. The pill mounts
#: behind a gate nobody had read: ``"confidential" === cost_string.toLowerCase()
#: && !is_partner_company``. Rows failing that gate answer 400 whatever id you
#: send them. Nothing was wrong with the earlier probes except their choice of
#: requisition, which is why re-running them could never have moved the answer.
#:
#: CAUTION, `is_partner_company` IS POLYMORPHIC: boolean on most authenticated
#: feed rows, a DATE STRING ("Jul 2026") on others, and a date string on every
#: row of the public index. A truthiness test on it silently classifies every
#: date-valued row as "partner" - that mistake produced a confident "0 rows
#: qualify" during this very investigation. Treat a truthy non-boolean as
#: UNKNOWN.
#:
#: WHAT IT RETURNS, and why it is worth having: `has_salary_data`,
#: `company_salary_p25` / `_p75`, a formatted `company_salary_range`, and
#: `company_matches`. Measured 3 of 6 gate-satisfying rows carrying real
#: percentiles. The gate fires exactly when `cost_string` is "Confidential" -
#: the case where the board shows no pay at all - so this is an estimated band
#: for precisely the requisitions whose salary is otherwise hidden.
#:
#: STILL NOT BUILT: no tool calls either route. That is a scope decision, not a
#: safety one - both are plain authenticated GETs returning company-level market
#: data.
EP_COMPANY_SALARY = "get-company-salary-data"         # GET ?hr_id=<row.id>
EP_COMPANY_DETAIL = "get-company-detail"              # GET ?hr_id=<row.id>

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
#: A mailbox is connected; the scan was never consented to.
#:
#: **THAT PARAGRAPH IS ABOUT A DIFFERENT CONSENT FROM THIS CONSTANT, and it
#: used to end by calling this "the route that flips it". It is not.** This
#: route is the GMAIL JOB-BOARD scan; `EP_INTERVIEW_LIST -> meta.has_consent`
#: is the INTERVIEW scan, a separate backend flag wearing the identical field
#: name, whose consent UI ships as CSS with no JSX behind it and which nothing
#: in Uplers' frontend can grant. The two were conflated here while nothing
#: called either one, so the error was inert; it stops being inert the moment
#: a tool wires this constant, which is what 2026-08-25 did. See
#: `agent_surface.CONSENT_AUTHORITY` and
#: `_audit/_slices/_slice-consent-semantics.md`, which established the split.
#:
#: WIRED 2026-08-25, and only its DELETE arm. `uplers_server.consent_write`
#: is the ONLY module that names this constant, and `uplers_revoke_email_scan`
#: hands it in as a sender - so the route is reachable from that one tool and
#: nowhere else, which
#: `tests/test_agent_tools.py::test_the_consent_write_constant_is_reachable_only_from_consent_write`
#: asserts by AST across every module in the package.
#:
#: THE VERBS ARE NOT SYMMETRICAL IN THIS SERVER even though they are on Uplers.
#: DELETE (revoke) is built. POST (grant, body a literal `{}`) is NOT: granting
#: starts a fresh mailbox scan, which is a decision of the same size as
#: stopping one and needs its own tool and its own preview rather than a
#: boolean parameter on this one.
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
