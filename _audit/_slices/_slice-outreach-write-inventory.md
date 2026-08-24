# Slice: outreach WRITE-route inventory (static analysis of the Uplers platform bundle)

Method: read-only static analysis of a local copy of the public JS bundle. ZERO network
requests were sent. No `mcp__uplers__*` tool was called. No POST, DELETE or authenticated
GET was issued against any Uplers host. Every line below comes from reading bytes in
`D:\claude-workspace\uplers-bundle\`.

Every claim is tagged **VERIFIED** (quoting bundle source) or **INFERRED** (reading intent).
Nothing is blurred between the two. Where a body is only a minified variable, it is quoted
verbatim and marked UNRESOLVED rather than guessed.

## Corpus

| artifact | value |
|---|---|
| `app.js` | 7,935,093 bytes -- matches the 2026-08-22 and 2026-08-23 records |
| lazy chunks | 85 chunks, 5,476,711 bytes total |
| local copy | `D:\claude-workspace\uplers-bundle\` (`app.js`, `chunks\`, `chunkmap.json`, `urls.txt`) |
| files searched | all 86 (13.4 MB) |

## Two departures from the brief, recorded up front

1. **The brief said "the four `talent/account/{linkedin,gmail}/*` routes". There are SIX.**
   The brief's own Q1 text then lists five (`linkedin/connect`, `linkedin/verify`,
   `linkedin/disconnect`, `gmail/verify`, `gmail/disconnect`), so "four" appears to be a
   miscount inside the brief. A sixth exists that the brief never names:
   **`talent/account/gmail/inbox/send`**. It is covered in section 4.6. This is additive,
   not contradictory, so the slice proceeded.
2. **A grep-tooling false negative worth recording for the next slice.** In Git Bash on
   Windows, MSYS path-mangling rewrites any argument that begins with `/`, so passing a
   pattern such as `/auth/login/gmail/` to a Python helper silently searches for a
   nonexistent Windows path and returns **zero matches** on a string that is genuinely
   present six times. Any negative result in this repo obtained from a leading-slash
   pattern must be re-run without the leading slash before it is believed. All negative
   findings in this document were re-verified with `grep` directly.

## Symbol-resolution chain used throughout

Three hops, each VERIFIED:

1. **Endpoint-constant module 81935** (`app.js` offsets 6921914 - 6930400) assigns each route
   to a short local: `var r="https://platform.uplers.com/", o=r+"api/", ... nt=o+"talent/outreach/store-message-template"`.
   173 locals extracted.
2. **The webpack re-export object** `.d(t,{...})` in the same module maps 201 mangled export
   keys to those locals: `uM3:()=>nt`, `kZJ:()=>vn`, `b8H:()=>Je`, ...
3. **Call sites** reference `X.<EXPORTKEY>`. The call sites are what this document reports;
   the constant declaration is not a call site.

Routes NOT in module 81935 are built inline at the call site, either as
`"".concat(X.H$l,"talent/outreach/...")` (`H$l` = the API base `o`) or as the literal
`"/api/talent/outreach/..."`. Both forms are covered.

### HTTP helper table (module 89687), VERIFIED

| export | body | verb |
|---|---|---|
| `Yr` (`A`) | `r.A.get(e)` | GET, URL only |
| `o$` (`E`) | `r.A.post(t,n,{headers:s})` | POST, url + body |
| `rn` (`P`) | `r.A.delete(e)` | DELETE, URL only, no body, no params |

Some call sites bypass the helpers and use raw axios (`v.A.post(...)`) with explicit
headers. Those are flagged per route.

### One methodological caveat on mangled keys

Mangled export keys are scoped **per module**. A bare `.KEY)(` search can therefore collide
across modules. Exactly one collision was hit and is recorded: `(0,u.vA)(N)` in chunk `1248`
at offset 196030 is a resume-health tracking call, **not** `talent/account/gmail/disconnect`
(its argument is the bare string `"resume-health-report"` and its surrounding scope reads
`resumeHealthReports`). It is excluded from the gmail/disconnect count. VERIFIED by context.

### Screen map (by `<title>` string, VERIFIED)

| chunk | screen |
|---|---|
| `305` | Pending Job \| Happpy Agent |
| `748` | (no title; byte-parallel twin of `9071`) Follow -- Outreach settings |
| `983` | Configure \| Happpy Agent |
| `1413` | Job activity \| Happpy Agent |
| `1625` | Dashboard \| Happpy Agent |
| `2063` | Interview Companies \| Happpy Agent |
| `2103` | Reply reminders \| Happpy Agent |
| `2268` | Subscription \| AgentJ |
| `2764` | (tailor/resume flow, no own title) |
| `2793` | Gmail OAuth callback page (route `/talent/gmail-connect/:token`) |
| `3474` | Recommended jobs \| Happpy Agent (owns the Gmail-scan tab) |
| `3574` | Happy Agent \| Welcome |
| `3805` | Job applications \| AgentJ |
| `4734` | (no title; byte-parallel twin of `8590`) Outreach Request |
| `5422` | Happpy Agent (dashboard shell / sidenav) |
| `5736` | Recommended jobs \| Happpy Agent |
| `6069` | Dashboard \| Happpy Agent |
| `6277` | Configure \| Happpy Agent (variant) |
| `6734` | My activity \| Happpy Agent |
| `7135` | External Jobs \| Happpy Agent |
| `7619` | Configure \| Happpy Agent (variant) |
| `8368` | Help guide / Raise a query |
| `8379` | Configure \| Happpy Agent |
| `8590` | Outreach Request \| AgentJ |
| `9071` | Follow -- Outreach settings \| AgentJ |

`748`/`9071` and `4734`/`8590` are near-identical byte-parallel chunk pairs (matching call
offsets within 5 bytes). INFERRED: a build emitted two variants of the same screen.

---

# 1. SUMMARY TABLE

Reversibility legend: **PAIRED** = an explicit inverse route exists (named).
**IDEMPOTENT-SETTINGS** = overwrites a record a GET can read back first, so the prior value
is recoverable by reading before writing (GET named). **ONE-WAY** = no inverse and no
readable prior state. **UNKNOWN** = could not be established (reason given).

## 1a. `talent/outreach/` WRITE routes -- 31 routes, 32 verb+route pairs

| # | route | verb | body (literal keys) | reversibility | screen |
|---|---|---|---|---|---|
| 1 | `consent-email-job-scan` | POST | `{}` (literal empty) | **PAIRED** -- DELETE same route | 3474 Recommended jobs |
| 2 | `consent-email-job-scan` | DELETE | none (URL only) | **PAIRED** -- POST same route | 3474 Recommended jobs |
| 3 | `settings/disabled-companies` | POST | `{company_id}` | **PAIRED** -- DELETE `settings/disabled-companies/{id}` | 748/9071, 8379 |
| 4 | `settings/disabled-companies/{id}` | DELETE | none (URL only) | **PAIRED** -- POST `settings/disabled-companies` | 748/9071, 8379 |
| 5 | `consent-auto-run` | POST | `{consent}` (Boolean) | **PAIRED** -- same route, `{consent:false}` | 8379 Configure |
| 6 | `settings/followup` | POST | 9 keys, see 3.6 | **IDEMPOTENT-SETTINGS** -- GET `settings/followup` | 748/9071, 8379 |
| 7 | `update-auto-reply` | POST | `{hours, handle_auto_reply, auto_reply_categories}` | **IDEMPOTENT-SETTINGS** -- GET `get-auto-reply` | 8379 Configure |
| 8 | `store-message-template` | POST | see 3.8 (two shapes) | **IDEMPOTENT-SETTINGS** -- GET `get-message-templates` | app, 5422, 6277, 7619, 8379, 983 |
| 9 | `store-recommended-jobs` | POST | `{jobs, auto_run, outreach_mode}` | **IDEMPOTENT-SETTINGS** -- GET `outreach-step` (`outreach_mode`) | app, 6277, 7619, 8379, 983 |
| 10 | `store-employee-requests` | POST | `{outreach_hr_id, persons[8 keys]}` | **ONE-WAY** -- UI copy says "cannot be undone" | 4734/8590, 6734 |
| 11 | `reveal-email` | POST | `{outreach_hr_id, outreach_employee_id}` | **ONE-WAY** | 4734/8590, 6734 |
| 12 | `discard-job` | POST | `{outreach_hr_id, feedback_reason, feedback_text}` | **ONE-WAY** | 4734/8590, 6734 |
| 13 | `auto-run-request` | POST | `{job_id, source, linkedin_message_id?, gmail_message_id?}` | **ONE-WAY** | 1625, 3474, 5736, 6069 |
| 14 | `external-apply-pending-jobs/{id}` | DELETE | none; `?external=0\|1` | **ONE-WAY** | 305 Pending Job, 6734 |
| 15 | `mark-as-seen` | POST | `{id, provider}` | **ONE-WAY** | 6734 My activity |
| 16 | `onboard-jobs-run-agent-complete` | POST | `{}` (literal empty) | **ONE-WAY** | 3574 Welcome |
| 17 | `feedback` | POST | `{rating, review_text, share_publicly, helped_most?, fix_feedback?}` | **ONE-WAY** | 1625, 5422 |
| 18 | `feedback/upload-media` | POST | multipart, field `file` | **ONE-WAY** | 1625, 5422 |
| 19 | `interview-feedback` | POST | `{company_id, feedback}` | **ONE-WAY** | 1625, 2063, 6069 |
| 20 | `support` | POST | `{message, page}` | **ONE-WAY** (GET `support?per_page&page` lists, cannot unsend) | 8368 Help guide |
| 21 | `invite-to-multiple-friends` | POST | `{invites[]}` | **ONE-WAY** | 5422 |
| 22 | `extend-free-trial` | POST | `{reason}` | **ONE-WAY** | app (subscribe modal) |
| 23 | `claim-discount-offer` | POST | `{plan_id}` | **ONE-WAY** | app (subscribe modal) |
| 24 | `claim-custom-light-plan` | POST | `{jobs}` | **ONE-WAY** | app (subscribe modal) |
| 25 | `claim-referral-code` | POST | `{happy_referral_code}` | **ONE-WAY** | app (onboarding) |
| 26 | `verify-referral-code` | POST | `{referral_code}` | **ONE-WAY** (read-only despite POST) | app (onboarding) |
| 27 | `subscribe-modal-action` | POST | `{action, context, button_label, screen_size}` | **ONE-WAY** (analytics) | app (subscribe modal) |
| 28 | `track-journey` | POST | `{key, data{screensize, ...}}` | **ONE-WAY** (analytics) | app (global helper) |
| 29 | `extension-engagement` | POST | `{chrome_extension_download}` | **ONE-WAY** (analytics) | app, 1625, 6277 |
| 30 | `rewrite-message` | POST | `{provider}` | **ONE-WAY** (generative; no client-side persistence observed) | app, 8379 |
| 31 | `refine-message` | POST | `{message}` | **ONE-WAY** (generative; no client-side persistence observed) | 1625, 5422 |
| 32 | `update-tailor-resume` | POST | `{id, resume}` | **UNKNOWN** -- see 3.32 | 2764 |

## 1b. `talent/account/` routes in scope -- 6 routes (brief said 4)

| # | route | verb | body | reversibility | screen |
|---|---|---|---|---|---|
| 33 | `talent/account/linkedin/connect` | POST | `{email, password}` | **PAIRED** -- `linkedin/disconnect` | app, 8379 |
| 34 | `talent/account/linkedin/verify` | POST | `{email, code}` | **PAIRED** -- `linkedin/disconnect` | app, 8379 |
| 35 | `talent/account/linkedin/disconnect` | POST | `{disconnect_reason}` | **PAIRED** -- `linkedin/connect` | app, 8379 |
| 36 | `talent/account/gmail/verify` | POST | `{token}` | **PAIRED** -- `gmail/disconnect` | 2793 OAuth callback |
| 37 | `talent/account/gmail/disconnect` | POST | `{disconnect_reason}` | **PAIRED** -- OAuth re-connect | app, 8379 |
| 38 | `talent/account/gmail/inbox/send` | (unknown) | (unknown) | **UNKNOWN** -- **ZERO CALL SITES** | none |

Adjacent, included because it is the outreach submit action and shares the `talent/account/`
prefix:

| # | route | verb | body | reversibility | screen |
|---|---|---|---|---|---|
| 39 | `talent/account/outreach-agent` | POST | `{hr_id, source, why_good_fit, is_tailored, html?, linkedin_message_id?, gmail_message_id?}` | **ONE-WAY** | app (referral drawer) |

## 1c. Routes under `talent/outreach/` that are NOT writes

Excluded from the inventory above, listed so the negative space is explicit. All VERIFIED
GET via the `Yr` helper or raw `axios.get` unless noted: `agent-plans`,
`agent-tailor-activity`, `default-auto-templates`, `external-job-link-remaining`,
`external-job-links-today`, `get-auto-reply`, `get-employee-requests`,
`get-external-apply-pending-jobs`, `get-last-health-check`, `get-message-templates`,
`get-outreach-agent`, `get-outreach-agent-meta`, `get-outreach-dashboard-data`,
`get-recommended-jobs`, `has-pending-action-manual-outreach-agent`, `interview-list`,
`job-description`, `missed-positive-reply-followups`,
`missed-positive-reply-followups-pending`, `onboard-jobs`, `outreach-step`,
`outreached-people`, `pending-jobs`, `preview-config`, `recommended-jobs-email`,
`recommended-jobs-meta-email`, `referral-list`, `settings/companies`,
`settings/disabled-companies` (GET arm), `settings/followup` (GET arm), `support` (GET arm),
`value-with-happy`.

**Not API routes at all** -- these match the string `talent/outreach/` but are `/images/`
asset paths, and would be a false positive for anyone grepping route strings naively.
VERIFIED, each preceded by `"/images/` or `url(/images/`: `create-profile-underline`,
`happpy-agent-favicon`, `leave-review/`, `mascot-chill`, `mascot-exclaim`,
`mascot-gmail-concern`, `mascot-insight`, `mascot-neutral`, `permission`,
`see-how-happpy-works-icon`, `sidenav-leave-review-sparkle`, `sidenav-logout-icon`,
`sidenav-need-help-icon`, `try-free-bg`, `works-anywhere/works-anywhere-left-bg`,
`works-anywhere/works-anywhere-right-bg`.

---

# 2. THE PROVIDER ENUM -- read this before building any message-template call

**`provider` is a NUMBER, not a string. `1` = LinkedIn, `2` = Gmail.** VERIFIED three ways.

Declaration (`app.js` offset 5383428, module 75329, immediately after the
`talent/outreach/mascot-insight.svg` constant in the same declaration cluster):

```js
ne="/images/talent/outreach/mascot-insight.svg",re={subject:"",body:""},oe=1,ie=2;
```

Use, at the `store-message-template` call site (offset 5389171) -- `ie` carries the
`gmail_template`, `oe` carries the `linkedin_template`:

```js
wt&&null!=ye&&ye.gmail_connected&&t.push({provider:ie,promise:(0,f.o$)(p.kZJ,{provider:ie,...
_t&&null!=ye&&ye.linkedin_connected&&t.push({provider:oe,promise:(0,f.o$)(p.kZJ,{provider:oe,...
```

and the response demux at offset 5389789:

```js
c===ie?r.gmail_message_id=u:c===oe&&(r.linkedin_message_id=u);
```

Independent confirmation with a **literal** `2`, chunk `8379` offset 8594 -- a gmail-template
save that hardcodes the numeral rather than the alias:

```js
var i={provider:2,message_template:o.message_template,message_subject:o.title||o.message_subject||""};
```

INFERRED: the same numeric enum governs `rewrite-message` (`{provider:e}` where the caller
compares `e===ie` for the Gmail branch, `app.js` @5395046) and `mark-as-seen`
(`{id:a,provider:n}`). Neither of those call sites carries a literal, so the enum identity
there is inference, not measurement.

---

# 3. PER-ROUTE EVIDENCE -- `talent/outreach/` writes

## 3.1 / 3.2 `consent-email-job-scan` -- POST and DELETE

Export key `Xkg`. Exactly 2 call sites, both chunk `3474`. Already documented in
`_slice-consent-semantics.md`; reproduced here for completeness of the write inventory.

POST (offset 96076), body is the **literal `{}`** -- VERIFIED:

```js
Ar=function(){...case 1:return qe(!0),U(""),e.p=2,e.n=3,(0,c.o$)(<Xkg>,{});case 3:return a=e.v,n=Z(a),
Ee(function(e){...{has_consent:!0,consent_email_job_scan:null==n?void 0:n.consent_email_job_scan,...
```

DELETE (offset 97194), URL only -- VERIFIED:

```js
case 0:if(!Je&&null!=Oe&&Oe.has_consent){e.n=1;break}return e.a(2);
case 1:return Qe(!0),U(""),e.p=2,e.n=3,(0,c.rn)(<Xkg>);
case 3:r=e.v,a=Z(r),Ee(function(e){...{has_consent:!1,consent_email_job_scan:null,...
```

- **Params:** none on either verb. VERIFIED.
- **Response read:** POST -> `res.data.data.{consent_email_job_scan, gmail_email}`;
  DELETE -> `res.data.data.{gmail_connected, gmail_email}`, both through
  `Z(e)= e.data.status===200 ? e.data.data : null`. VERIFIED.
- **Reversibility: PAIRED.** The inverse of the POST is the DELETE on the identical URL.
  VERIFIED -- both are literally the same constant `Xkg`.
- Guard worth copying (VERIFIED): the POST is gated on a local acknowledgement checkbox
  (`if(er&&!We)`), the DELETE on `Oe.has_consent` already being true. The UI can never reach
  the POST while consent is already granted.

## 3.3 / 3.4 `settings/disabled-companies` -- POST add, DELETE remove

Inline route strings, chunk `748` (twin `9071`) and chunk `8379`.

POST (`748` @13095) -- VERIFIED:

```js
case 1:return I(!0),e.p=2,e.n=3,(0,r.o$)("".concat(i.H$l,"talent/outreach/settings/disabled-companies"),{company_id:n.id});
case 3:200===(...l.data.status)?(a(function(e){return[l.data.data].concat(m(e))}),b(""),S([]),
  o.oR.success("Company added to disabled list")):o.oR.error(...||"Failed to add company"),
```

DELETE (`748` @13890) -- VERIFIED, id as a **path segment**, no body:

```js
case 0:return e.p=0,e.n=1,(0,r.rn)("".concat(i.H$l,"talent/outreach/settings/disabled-companies/").concat(n));
case 1:200===(...l.data.status)?(a(function(e){return e.filter(function(e){return e.id!==n})}),
  o.oR.success("Company removed from disabled list")):o.oR.error(...||"Failed to remove"),
```

- **Body:** POST `{company_id: <company.id>}`. DELETE none. VERIFIED.
- **Path parameter:** DELETE takes `{id}` appended to the route. VERIFIED.
- **Response read:** POST -> `res.data.data` is the created row, unshifted onto the list.
  DELETE -> only `res.data.status === 200` is checked. VERIFIED.
- **Reversibility: PAIRED.** The success toasts name the pair verbatim: "Company added to
  disabled list" / "Company removed from disabled list". VERIFIED.
- The companion GET `settings/disabled-companies` (no id) lists the current set, and
  `settings/companies?search=<term>` is the typeahead used to pick one. VERIFIED.

## 3.5 `consent-auto-run` -- POST

Export key `YfT`. Exactly 1 call site, chunk `8379` @62197 -- VERIFIED:

```js
case 1:return r=l,h(n),g(!0),t.p=2,t.n=3,(0,p.o$)(u.YfT,{consent:Boolean(n)});
case 3:200===(null==(o=t.v)||null===(a=o.data)||void 0===a?void 0:a.status)
  ?(e((0,s.CA)(n)),c.oR.success("HAPPPY auto run ".concat(n?"enabled":"disabled")))
  :(x.current&&h(r),c.oR.error("Failed to update")),
```

- **Body:** `{consent: Boolean(n)}`. VERIFIED.
- **Response read:** `res.data.status === 200` only. VERIFIED.
- **Reversibility: PAIRED.** The same route with `{consent:false}` is the inverse -- the
  toast string `"HAPPPY auto run " + (n?"enabled":"disabled")` proves both directions run
  through this one call. VERIFIED.
- Prior value is recoverable without writing: `GET get-outreach-dashboard-data ->
  data.auto_run_consent` is the field the toggle displays. VERIFIED (see
  `_slice-consent-semantics.md` Q4). Note the handler stashes the old value in `r` and rolls
  back locally on failure, but **no route is refetched** after the write.

## 3.6 `settings/followup` -- POST  (Q3)

See section 6 (Q3) for the full quoted call site and the partial-body answer.

## 3.7 `update-auto-reply` -- POST

Inline route. 2 call sites (`app.js` @5391603, chunk `8379` @73141). Chunk `8379` -- VERIFIED:

```js
case 0:if(!t.handle_auto_reply||0!==t.auto_reply_categories.length){e.n=1;break}
  return c.oR.error("Select at least one category to enable auto-reply"),e.a(2);
case 1:return h(!0),e.p=2,e.n=3,(0,p.o$)("".concat(u.H$l,"talent/outreach/update-auto-reply"),
  {hours:Ge(t.hours),handle_auto_reply:Boolean(t.handle_auto_reply),auto_reply_categories:t.auto_reply_categories});
case 3:200===(...r.data.status)?c.oR.success("Auto-reply settings saved"):c.oR.error(...||"Failed to save"),
```

- **Body:** `{hours, handle_auto_reply, auto_reply_categories}` -- all three always sent,
  read off one form-state object `t`. VERIFIED.
- **Validation gate (VERIFIED):** enabling with an empty `auto_reply_categories` array is
  refused client-side.
- **Response read:** `res.data.status === 200`. VERIFIED.
- **Reversibility: IDEMPOTENT-SETTINGS.** The read-back is **`GET talent/outreach/get-auto-reply`**
  (`Yr` at `app.js` @5390519 and `8379` @72114, no params), whose `.data.data` seeds the same
  form state. VERIFIED. Read it before writing to recover the prior record.

## 3.8 `store-message-template` -- POST  (Q2)

See section 5 (Q2) for the full quoted call sites, the two body shapes, and the
one-channel-per-request answer.

## 3.9 `store-recommended-jobs` -- POST

Export key `aP`, reached through the redux thunk `bX` (`gt` in module 26878). Thunk
(`app.js` @1606835) -- VERIFIED:

```js
gt=function(e){return function(t){return t({type:a.rQ,payload:!0}),new Promise(function(n,r){
  (0,i.o$)(o.aP,e).then(function(e){n(e)}).catch(function(e){r(e)})
  .finally(function(){return t({type:a.rQ,payload:!1})})})}}
```

The thunk body is the bare minified parameter `e` -- UNRESOLVED at the thunk. Traced to its
callers: **8 call sites**, all with the identical three-key literal. VERIFIED:

```js
// app.js @4525430   (agent onboarding, mode step)
(0,k.bX)({jobs:[],auto_run:p===xp,outreach_mode:p})
// chunks 6277 @4503, 7619 @4503, 983 @4509   (Configure, "save preferences")
(0,a.bX)({jobs:[],auto_run:"auto"===g,outreach_mode:g})
// chunks 6277 @5084, 7619 @5084, 983 @5090   (Configure, mode radio)
(0,a.bX)({jobs:[],auto_run:"auto"===t,outreach_mode:t})
// chunk 8379 @83772   (Configure screen, mode change)
(0,s.bX)({jobs:[],auto_run:t===Xe,outreach_mode:t})
```

- **Body:** `{jobs, auto_run, outreach_mode}`. VERIFIED.
- **`jobs` is `[]` at every one of the 8 call sites.** VERIFIED -- there is no shipped code
  path that sends a non-empty `jobs` array to this route, despite the route's name. INFERRED:
  the jobs arm is server-supported but unused by this build, or vestigial.
- **`auto_run` is derived, never read back:** `auto_run = (mode === "auto")`. The UI reads
  back `outreach_mode`, never `auto_run`. VERIFIED exhaustively in
  `_slice-consent-semantics.md` Q4 (8 occurrences, all writes, zero reads).
- **Response read:** nothing, at every call site. VERIFIED.
- **Reversibility: IDEMPOTENT-SETTINGS.** The read-back is **`GET talent/outreach/outreach-step`**,
  which the `8379` handler calls immediately after the write:
  `n((0,s.rq)({silent:!0,force:!0}))`. VERIFIED. `outreach-step` echoes `outreach_mode`, so
  the prior mode is recoverable by reading first.

## 3.10 `store-employee-requests` -- POST

Inline route `"/api/talent/outreach/store-employee-requests"`. 3 call sites
(`4734` @64311, `8590` @64693, `6734` @360722), identical. `4734` -- VERIFIED:

```js
case 1:return ne(!0),e.p=2,
  t=o.map(function(e){return{
    outreach_employee_id:e.id,
    linkedin_channel_reach:!e.removed&&(e.linkedinEnabled||!1),
    gmail_channel_reach:!e.removed&&(e.gmailEnabled||!1),
    linkedin_url:e.linkedinUrl||null,
    gmail_email:e.email||null,
    linkedin_custom_message:e.linkedinMsg||Ye.linkedinMessage||null,
    gmail_custom_message:e.gmailMsg||Ye.gmailMessage||null,
    gmail_custom_message_subject:e.gmailSubject||Ye.gmailSubject||null}}),
  r={outreach_hr_id:$,persons:t},e.n=3,(0,l.o$)("/api/talent/outreach/store-employee-requests",r);
case 3:200===(...)||"success"===(...)?(d=s.data.data||{},c=d.created_count,p=d.skipped_count,
  me({created:c||0,skipped:p||0}),le(!0),G(function(e){return e.filter(function(e){return e.id!==$})}))
```

- **Body:** `{outreach_hr_id, persons:[{outreach_employee_id, linkedin_channel_reach,
  gmail_channel_reach, linkedin_url, gmail_email, linkedin_custom_message,
  gmail_custom_message, gmail_custom_message_subject}]}` -- 2 top-level keys, 8 per person.
  VERIFIED, built from a form state map `ge` keyed by person id, with per-person overrides
  falling back to a shared default `Ye`.
- **Client-side gate (VERIFIED):** refuses with "No persons selected" unless at least one
  person is `!removed && (linkedinEnabled || gmailEnabled)`.
- **Response read:** `res.data.data.{created_count, skipped_count}`. VERIFIED. Note the
  status check accepts **either** `status === 200` **or** `status === "success"` -- this
  route's envelope is not consistent with the rest of the surface.
- **Reversibility: ONE-WAY.** This is the outreach send. No inverse route exists anywhere in
  13.4 MB. The confirm copy is explicit, VERIFIED verbatim in chunks 4734/6734/8590:
  *"Once confirmed, our Happpy Agent will reach out to these contacts on your behalf. This
  action cannot be undone."*

## 3.11 `reveal-email` -- POST

Inline route. 3 call sites (`4734` @60667, `8590` @61049, `6734` @357078). VERIFIED:

```js
case 1:return ao(function(e){return g(g({},e),{},u({},o,!0))}),e.p=2,e.n=3,
  (0,l.o$)("/api/talent/outreach/reveal-email",{outreach_hr_id:$,outreach_employee_id:o});
case 3:200===(...)||"success"===(...)?(s=null===(r=t.data.data)||void 0===r?void 0:r.email)&&(
  no(function(e){return g(g({},e),{},u({},o,s))}),
  ue(function(e){return g(g({},e),{},u({},o,g(g({},e[o]),{},{email:s})))}),uo("...
```

- **Body:** `{outreach_hr_id, outreach_employee_id}`. VERIFIED.
- **Response read:** `res.data.data.email`. VERIFIED.
- **Reversibility: ONE-WAY.** No un-reveal route exists. INFERRED (strong): revealing is a
  metered disclosure, so a client should treat each call as spending something.

## 3.12 `discard-job` -- POST

Inline route. 3 call sites (`4734` @62829, `8590` @63211, `6734` @359240). VERIFIED:

```js
case 0:return ae(!0),e.p=1,e.n=2,(0,l.o$)("/api/talent/outreach/discard-job",
  {outreach_hr_id:$,feedback_reason:Ae,feedback_text:Ue});
case 2:200===(...)||"success"===(...)?(Re(!1),pe(!0),
  G(function(e){return e.filter(function(e){return e.id!==$})}))
  :a.oR.error(...||"Failed to discard job"),
```

- **Body:** `{outreach_hr_id, feedback_reason, feedback_text}`. VERIFIED.
- **Response read:** status only; the row is filtered out of the local list. VERIFIED.
- **Reversibility: ONE-WAY.** No un-discard route. Contrast with the jobs-board's
  `talent/hr/job-not-interested`, which DOES carry an explicit
  `{hr_number, reset_not_interested:true}` undo -- that reversal does not apply here, this is
  a different subsystem with a different id space (`outreach_hr_id`, not `HR_Number`).

## 3.13 `auto-run-request` -- POST

Export key `Tsc`. 4 call sites (`1625` @101282, `3474` @98915, `5736` @9610, `6069` @11295).
`1625` -- VERIFIED:

```js
case 0:if(n=(t=s.length>0&&void 0!==s[0]?s[0]:{}).linkedin_message_id,a=t.gmail_message_id,
  null!=(null==Pe?void 0:Pe.id)){e.n=1;break}return Te(null),e.a(2);
case 1:return r=Pe.id,Te(null),Se(r),e.p=2,
  i={job_id:r,source:"happpy-dashboard"},
  n&&(i.linkedin_message_id=n),a&&(i.gmail_message_id=a),
  e.n=3,(0,d.o$)(c.Tsc,i);
case 3:x((0,p.dg)()),Ae(function(e){return $e($e({},e),{},Ke({},r,!0))}),
```

- **Body:** `{job_id, source}` always, plus `linkedin_message_id` and/or `gmail_message_id`
  **only when truthy** -- conditional keys, VERIFIED.
- **`source` is the literal `"happpy-dashboard"`** at this site. VERIFIED.
- **Response read:** nothing; a redux refetch `(0,p.dg)()` follows. VERIFIED.
- **Reversibility: ONE-WAY.** This dispatches the agent at a job. No cancel route.

## 3.14 `external-apply-pending-jobs/{id}` -- DELETE

Inline route. 2 call sites (`305` @35327, `6734` @172913). `305` -- VERIFIED:

```js
case 1:return r=f(a=w),n=a.external?"1":"0",e.p=2,m(r),e.n=3,
  (0,o.rn)("".concat(l.H$l,"talent/outreach/external-apply-pending-jobs/").concat(a.id,"?external=").concat(n));
case 3:200===(...s.data.status)?(i.oR.success(...||"Job removed from pending queue"),
  t(function(e){return e.filter(function(e){return f(e)!==r})}),j(null))
```

- **Path parameter:** `{id}` = `job.id`. **Query parameter:** `?external=0|1`, derived from
  `job.external`. VERIFIED. Note this is a DELETE that carries a query string -- the `rn`
  helper takes the fully-built URL, so the query survives.
- **Body:** none. The `rn` helper is `r.A.delete(e)` -- URL only. VERIFIED.
- **Response read:** `res.data.status`, `res.data.message`. VERIFIED.
- **Reversibility: ONE-WAY.** No route re-adds a job to the pending queue.

## 3.15 `mark-as-seen` -- POST

Export key `s12`, via thunk `Ht` (export `XS`) in module 26878. Thunk (`app.js` @1614998) --
VERIFIED, body is the bare parameter `e`, UNRESOLVED at the thunk:

```js
Ht=function(e){return new Promise(function(t,n){(0,i.o$)(o.s12,e).then(function(e){t(e)}).catch(function(e){n(e)})})}
```

Traced to its **single** caller, chunk `6734` @125611 -- VERIFIED:

```js
V=function(e,a,n){(0,c.XS)({id:a,provider:n}).then(function(){
  t(function(t){return t.map(function(t){return t.id===e?x(x({},t),{},{replies:t.replies.map(
    function(e){return e.id===a?x(x({},e),{},{seen:1}):e})}):t})})
}).catch(function(e){console.log(e)})}
```

- **Body:** `{id, provider}` where `id` is the **reply** id (not the job id) and `provider`
  is the numeric channel enum. VERIFIED for the key names; the enum identity here is INFERRED
  from section 2 (no literal at this site).
- **Response read:** nothing; the row is locally set to `seen:1`. VERIFIED.
- **Reversibility: ONE-WAY.** No mark-as-unseen route exists.

## 3.16 `onboard-jobs-run-agent-complete` -- POST

Export key `M65`. Exactly 1 call site, chunk `3574` @30053 -- VERIFIED:

```js
(0,o.useEffect)(function(){w.current||(w.current=!0,(0,s.o$)(i.M65,{}).catch(function(){}))},[])
```

- **Body:** the literal `{}`. VERIFIED.
- **Fire-and-forget:** `.catch(function(){})` swallows all errors; nothing is read from the
  response. Guarded by a `useRef` so it fires at most once per mount. VERIFIED.
- **Reversibility: ONE-WAY.** Marks onboarding complete; no inverse.

## 3.17 `feedback` -- POST (raw axios)

Export key `TOR`. 2 call sites (`1625` @23843, `5422` @61482), both **raw axios**, not the
`o$` helper. `1625` -- VERIFIED:

```js
case 0:return n=k({},t),
  Array.isArray(n.negative_reasons)&&n.negative_reasons.length&&(n.helped_most=n.negative_reasons),
  n.negative_detail&&(n.fix_feedback=n.negative_detail),
  delete n.negative_reasons,delete n.negative_detail,
  a=localStorage.getItem("token"),e.n=1,
  v.A.post(c.TOR,n,{headers:{Authorization:"Bearer ".concat(a),Accept:"application/json","Content-Type":"application/json"}});
case 1:if(r=e.v,"success"===(i=(null==r?void 0:r.data)||{}).status){e.n=2;break}throw new Error(i.message||...
```

The base object `t` is traced to two producers in the same chunk. VERIFIED:

```js
// @32942 -- the review payload builder
fe=(0,a.useCallback)(function(){return{rating:h.rating,review_text:se,share_publicly:Boolean(h.sharePublicly)}},...)
// @31646 -- the negative-detail follow-up, spreading the stashed review payload L
t=R(R({},L),{},{negative_reasons:C.reasons,negative_detail:C.detailText.trim()||null}),...,S(t)
// @33923 -- L is set from fe()
n=fe(), ... O(n)
```

- **Body, shape A (plain review):** `{rating, review_text, share_publicly}`. VERIFIED.
- **Body, shape B (review + negative detail):** `{rating, review_text, share_publicly,
  helped_most, fix_feedback}` -- note the **client-side rename**: `negative_reasons` is sent
  as `helped_most` and `negative_detail` as `fix_feedback`, and the original two keys are
  `delete`d before the POST. A client that sends `negative_reasons` is sending a key this UI
  never sends. VERIFIED.
- **Headers:** explicit `Content-Type: application/json` and a bearer token read straight from
  `localStorage`; the `o$` helper's UTM headers are **not** sent. VERIFIED.
- **Response read:** `res.data.status === "success"`, `res.data.message`. VERIFIED.
- **Reversibility: ONE-WAY.**

## 3.18 `feedback/upload-media` -- POST (multipart)

Export key `CZy`. 2 call sites (`1625` @18369, `5422` @369956). VERIFIED:

```js
case 0:return d=(c=_.length>1&&void 0!==_[1]?_[1]:{}).signal,p=c.onProgress,
  (h=new FormData).append("file",t),
  u=localStorage.getItem("token"),e.p=1,e.n=2,
  a.A.post(r.CZy,h,{headers:{Authorization:"Bearer ".concat(u),"Content-Type":"multipart/form-data"},
    signal:d,onUploadProgress:function(e){p&&e.total&&p(Math.round(e.loaded/e.total*100))}});
```

- **Body:** `FormData` with exactly one field, `file`. **This is the only multipart write in
  the outreach surface.** VERIFIED.
- Supports an `AbortController` signal and an upload-progress callback. VERIFIED.
- **Reversibility: ONE-WAY.** No delete-media route.

## 3.19 `interview-feedback` -- POST

Inline route. 4 occurrences / 3 distinct screens (`1625` @6174, `2063` @5922, `6069` @42788).
VERIFIED:

```js
b({companyId:t,feedback:n}),e.p=1,e.n=2,(0,i.o$)("".concat(r.H$l,"talent/outreach/interview-feedback"),{company_id:t,feedback:n});
case 2:if(a=e.v,"success"!==(null==(s=null==a?void 0:a.data)?void 0:s.status)){...}
```

- **Body:** `{company_id, feedback}`. VERIFIED.
- **Response read:** `res.data.status === "success"`; errors at `res.data.message` or
  `res.data.errors.feedback[0]`. VERIFIED.
- **Reversibility: ONE-WAY.** On success the UI patches the row's `feedback` in place. There
  is no delete or edit route; a second POST for the same `company_id` is the only way to
  change it, and whether the server treats that as an overwrite is NOT decidable from the
  bundle.

## 3.20 `support` -- POST (and a GET on the same route)

Export key `Rl4`. 3 call sites: 1 POST in `app.js` @1611081 (thunk), 1 POST and 1 GET in
chunk `8368`. POST (`8368` @13814) -- VERIFIED:

```js
case 1:return f(!0),e.p=2,e.n=3,(0,c.o$)(d.Rl4,
  {message:t,page:"AgentJ / Job agent / Help Guide / Raise a Query"});
case 3:r=e.v,n=200===(...r.data.status),l=...r.data.message,
  n?(O(l||"Query submitted."),G(""),ne(1)):T(l||...||"Could not submit query."),
```

GET on the same constant (`8368` @12398) -- VERIFIED:

```js
j="".concat(d.Rl4,"?per_page=").concat(10,"&page=").concat(a),e.n=2,(0,c.Yr)(j);
```

- **Body:** `{message, page}` where `page` is a hardcoded breadcrumb string. VERIFIED.
- **Query (GET arm):** `?per_page=10&page=<n>`. VERIFIED.
- **Reversibility: ONE-WAY.** The GET lists tickets, so the write is *observable*, but no
  route deletes or edits a submitted ticket. Not IDEMPOTENT-SETTINGS: the POST appends a
  ticket, it does not overwrite a record.

## 3.21 `invite-to-multiple-friends` -- POST

Export key `e5S`. 1 call site, chunk `5422` @20263 -- VERIFIED:

```js
case 3:return f(!0),e.p=4,e.n=5,(0,b.o$)(p.e5S,{invites:t});
case 5:200===(...c.data.status)?(m.Ay.success(...||"Invites sent successfully."),r([]),i(""),s(""))
  :m.Ay.error(...||"Could not send invites."),
```

- **Body:** `{invites: [<string>]}` -- an array of validated identifiers. The validator
  accepts an email **or** a 10-digit mobile number; the error copy is verbatim
  *"Enter a valid email or 10-digit Mobile number."* VERIFIED.
- **Reversibility: ONE-WAY.** Invites are sent; no recall route.

## 3.22 - 3.26 The commercial claim routes

All 5 are single-call-site POSTs in `app.js`, all in the subscribe/onboarding modals. Bodies
are literal at the call site. VERIFIED:

| route | export | offset | body | response read |
|---|---|---|---|---|
| `extend-free-trial` | `ymq` | 5336780 | `{reason: extendReason \|\| "explore"}` | `status==="success"`, `data.message` |
| `claim-discount-offer` | `vwU` | 5337618 | `{plan_id: Number(n)}` | `data.data.{agent_tailor_plans, agent_tailor_plans_original, redirect_url}` |
| `claim-custom-light-plan` | `H37` | 5338793 | `{jobs: Number(ee)}` | same as above |
| `claim-referral-code` | `gpR` | 4477722 | `{happy_referral_code: n}` | `data.data.referral_from` |
| `verify-referral-code` | `Xvo` | 4477363 | `{referral_code: n}` | `data.data.already_claimed` |

Quoted, `claim-custom-light-plan` (note the client-side range gate) -- VERIFIED:

```js
case 1:if(n=Number(ee),!(!Number.isInteger(n)||n<E||n>T)){e.n=2;break}
  return c.oR.error("Choose between ".concat(E," and ").concat(T," jobs")),e.a(2);
case 2:return W(!0),e.p=3,e.n=4,(0,f.o$)(p.H37,{jobs:n});
```

and the verify -> claim sequence, which is the one place two of these chain -- VERIFIED:

```js
case 3:De.current=n,pe("verifying"),e.p=4,e.n=5,(0,Z.o$)(b.Xvo,{referral_code:n});
case 5:if(200===(null==(o=e.v)?void 0:o.status)){e.n=6;break}return pe("invalid"),me(""),e.a(2,!1);
case 6:if(...!r.already_claimed){e.n=7;break}return pe("verified"),me(n),ye(!0),
  J.oR.success("Referral code already claimed !"),e.a(2,!0);
case 7:return e.n=8,(0,Z.o$)(b.gpR,{happy_referral_code:n});
```

- **Reversibility: all ONE-WAY.** No un-claim, un-extend or un-apply route exists.
- **`verify-referral-code` is a read in POST clothing** (INFERRED, strong): it only sets
  local validation state and gates whether `claim-referral-code` fires. It is nonetheless a
  POST and is listed as a write on that basis.
- **Note the field-name asymmetry (VERIFIED):** the verify route takes `referral_code`, the
  claim route takes `happy_referral_code`. Same value, two names, two routes.

## 3.27 - 3.29 The analytics writes

| route | export / form | body | notes |
|---|---|---|---|
| `subscribe-modal-action` | `h22`, app.js @5416336 | `{action, context, button_label, screen_size}` | `context` and `button_label` are `\|\| undefined`; `screen_size` from a helper `(0,f.FL)()` |
| `track-journey` | `gnG`, app.js @2891427 | `{key, data:{screensize, ...extra}}` | short-circuits to a fake resolved promise when there is no `localStorage` token |
| `extension-engagement` | inline, app.js @4508902 + `1625` @79424 + `6277` @20532 | `{chrome_extension_download:true}` | fire-and-forget `.catch(function(){})` |

`track-journey`, quoted in full because its no-auth short-circuit matters -- VERIFIED:

```js
function f(e){var t=arguments.length>1&&void 0!==arguments[1]?arguments[1]:{};
  if(!e||"string"!=typeof e)return Promise.resolve({status:200,data:{message:"No journey key"}});
  if(!("undefined"!=typeof localStorage?localStorage.getItem("token"):null))
    return Promise.resolve({status:200,data:{message:"Tracking skipped (not authenticated)"}});
  var n={key:e,data:l({screensize:(0,i.FL)()},t&&"object"===a(t)?t:{})};
  return (0,i.o$)(o.gnG,n)}
```

- **Reversibility: all three ONE-WAY.** Analytics appends; nothing reverses them.

## 3.30 `rewrite-message` -- POST

Export key `_u`. 2 call sites (`app.js` @5395046, `8379` @12918). `app.js` -- VERIFIED:

```js
Dt=function(e){Ae(e),(0,f.o$)(p._u,{provider:e}).then(function(t){var n,r;
  if("success"===(null===(n=t.data)||void 0===n?void 0:n.status)&&null!==(r=t.data)&&void 0!==r&&r.data){
    var o=t.data.data,i=o.message,a=o.subject;
    ve(function(t){return t?q(q({},t),{},e===ie
      ?{gmail_template:q(q({},t.gmail_template),{},{message:i},a?{subject:a}:{})}
      :{linkedin_template:q(q({},t.linkedin_template),{},{message:i})}):t})}})
```

- **Body:** `{provider}` -- the numeric enum, nothing else. VERIFIED.
- **Response read:** `res.data.data.{message, subject}`. `subject` is only merged in on the
  Gmail branch. VERIFIED.
- **Reversibility: ONE-WAY** in the sense that no inverse route exists. But INFERRED (strong):
  this is a **generative compute call, not a state write** -- the result is written only into
  React state, and persisting it requires a separate `store-message-template` POST. A client
  can call it without changing stored server state, though whether the server meters it is
  not decidable from the bundle.

## 3.31 `refine-message` -- POST (raw axios)

Export key `HZG`. 2 call sites (`1625` @34736, `5422` @59735). VERIFIED:

```js
case 1:return t=h.reviewText,ie.current&&ie.current.abort(),n=new AbortController,ie.current=n,I(!0),e.p=2,
  r=localStorage.getItem("token"),e.n=3,
  v.A.post(c.HZG,{message:t.trim()},{headers:{Authorization:"Bearer ".concat(r),Accept:"application/json",
    "Content-Type":"application/json"},signal:n.signal});
case 3:if(i=e.v,"success"===(s=(null==i?void 0:i.data)||{}).status&&null!==(a=s.data)&&void 0!==a&&a.message){e.n=4;break}
  throw new Error(s.message||"Failed to refine review.");
```

- **Body:** `{message}` -- trimmed. VERIFIED.
- **Raw axios**, explicit headers, `AbortController` (a new request aborts the previous one).
  VERIFIED.
- **Client-side gate (VERIFIED):** "Write at least 10 characters before tidying."
- **Reversibility: ONE-WAY**, same generative-not-persisting caveat as `rewrite-message`.

## 3.32 `update-tailor-resume` -- POST

Export key `HpX`, via thunk `d` (export `fr`) in module 15926. Thunk (`app.js` @581734) --
body is the bare parameter `e`, UNRESOLVED at the thunk. VERIFIED:

```js
d=function(e){return function(t){return new Promise(function(n,s){
  (0,o.o$)(r.HpX,e).then(function(e){n(e)}).catch(function(e){
    e.response&&e.response.status&&401==e.response.status&&(0,a.a1)()(t),s(e)})
  .finally(function(){t({type:i.rQ,payload:!1})})})}}
```

Traced to its **single** caller, chunk `2764` @194796 -- VERIFIED:

```js
(0,ne.fr)({id:ft,resume:r})(We).then(function(e){
  g.Ay.success("Tailored resume updated successfully !");
  try{window.dispatchEvent(new CustomEvent("job-agent:tailor-updated",{detail:{activeOutreachHrId:ft}}))}catch(e){}
}).catch(function(e){console.log("err",e)}),
ke&&null!=_e&&(0,j.o$)(L.H5q,{id:_e,action:4,resume:r}).catch(function(){})
```

- **Body:** `{id, resume}`. VERIFIED.
- **Response read:** nothing; a success toast plus a `CustomEvent` broadcast. VERIFIED.
- **Reversibility: UNKNOWN.** Stated as UNKNOWN rather than guessed, for a specific reason:
  the write overwrites a stored tailored resume, and a read-back plausibly exists under the
  `talent/tailor/*` family (`talent/tailor/create`, `/update`, `/download`, `/match` are all
  present in module 81935). But **no `talent/tailor/*` route is in this slice's scope**, and
  I did not resolve whether any of them returns the same `resume` field this route writes.
  Classifying it IDEMPOTENT-SETTINGS would require naming the GET, which I cannot do from
  within scope. It is not ONE-WAY either, since it is an overwrite of an addressable record.
  Resolving this needs a follow-up slice over the `talent/tailor/` surface.

---

# 4. PER-ROUTE EVIDENCE -- `talent/account/` routes

All six live in one declaration run in module 81935, `app.js` @6927299 -- VERIFIED verbatim:

```js
Ge=o+"talent/account/status",$e=o+"talent/account/analytics",
Je=o+"talent/account/linkedin/connect",Ze=o+"talent/account/linkedin/verify",
Ke=o+"talent/account/linkedin/disconnect",Qe=o+"talent/account/gmail/verify",
Xe=o+"talent/account/gmail/disconnect",et=o+"talent/account/gmail/inbox/send",
tt=o+"talent/account/outreach-agent",
```

The service thunks are consecutive in module 26878, `app.js` @1601958 -- VERIFIED verbatim.
Note that **every body here is the bare minified parameter `e`** at the thunk, and two of
them use the `null!=e?e:{}` idiom the brief asked to be quoted verbatim:

```js
Xe=function(e){return function(t){return new Promise(function(n,r){(0,i.o$)(o.b8H,e)...})}},   // linkedin/connect
et=function(e){return function(t){return t({type:a.rQ,payload:!0}),new Promise(function(n,r){(0,i.o$)(o.E0C,e)...})}},   // linkedin/verify
tt=function(e){return function(t){return new Promise(function(n,r){(0,i.o$)(o.l2$,null!=e?e:{})...})}},   // linkedin/disconnect
nt=function(e){return function(t){return t({type:a.rQ,payload:!0}),new Promise(function(n,r){(0,i.o$)(o.OVx,e)...})}},   // gmail/verify
rt=function(e){return function(t){return new Promise(function(n,r){(0,i.o$)(o.FE,null!=e?e:{})...})}},   // gmail/disconnect
ot=function(e){return function(t){return new Promise(function(n,r){(0,i.o$)(o.NgJ,e)...})}},   // account/outreach-agent
```

`null!=e?e:{}` on `linkedin/disconnect` and `gmail/disconnect` means **both disconnect routes
accept being called with no argument at all**, in which case an empty object is POSTed.
VERIFIED. Every shipped caller does pass a reason, so the empty-body branch is reachable but
unexercised in this build.

All bodies below were resolved by tracing the thunk export keys (`zC`, `qN`, `jV`, `zW`,
`vA`, `rz`) to their callers.

## 4.1 `talent/account/linkedin/connect` -- POST

3 call sites (`app.js` @3681229, `app.js` @4479082, `8379` @23662), identical bodies. VERIFIED:

```js
case 2:return B(!0),de({type:null,text:""}),e.p=3,_e("happy_agent_linkedin_connect_attempted"),e.n=4,
  S((0,i.zC)({email:O.email,password:O.password}));
case 4:s=e.v,J(...s.data.data),
  2==(...s.data.data.status)?(de({type:"success",text:"LinkedIn account connected successfully!"}),
    Fe(),_e("happy_agent_linkedin_connected"),localStorage.setItem("outreach_account_connected","true"),...
```

- **Body:** `{email, password}` -- **the user's LinkedIn password, posted to Uplers' API.**
  VERIFIED. This is the load-bearing asymmetry behind Q1: see section 4.7.
- **Response read:** `res.data.data`, with `res.data.data.status === 2` meaning connected and
  `=== 1` handled as a separate branch (INFERRED: "verification required", since the
  neighbouring verify handler keys off `auth_type === "code_required"`).
- **Reversibility: PAIRED** -- `talent/account/linkedin/disconnect`.

## 4.2 `talent/account/linkedin/verify` -- POST

3 call sites (`app.js` @3686551, `app.js` @4480521, `8379` @24990). VERIFIED:

```js
e.n=4,S((0,i.qN)({email:O.email,code:null==O?void 0:O.code}));
case 4:2==(...r.data.data.status)?(de({type:"success",text:"LinkedIn account verified and connected successfully!"}),
  _e("happy_agent_linkedin_verified"),J(...r.data.data),...
  ):("code_required"==(...)? "Invalid verification code" ...
```

- **Body:** `{email, code}`. VERIFIED.
- **Reversibility: PAIRED** -- part of the connect flow; reversed by `linkedin/disconnect`.

## 4.3 `talent/account/linkedin/disconnect` -- POST

3 call sites (`app.js` @3682833, `app.js` @4481595, `8379` @26046). VERIFIED:

```js
case 0:return e.p=0,_e("happy_agent_linkedin_disconnect_attempted"),e.n=1,S((0,i.jV)({disconnect_reason:t}));
case 1:"success"===(...o.data.status)?(J(null),se(!1),L({email:"",password:"",code:""}),de({type:null,text:""}),
  l.oR.success(n),_e("happy_agent_linkedin_disconnected"),m&&m()):l.oR.error(...||"Something went wrong. Please try again."),
```

- **Body:** `{disconnect_reason}` -- a single free-text/enum reason. VERIFIED.
- **Response read:** `res.data.status === "success"` (**string**, unlike connect/verify which
  read a numeric `data.status`). Two different status conventions on adjacent routes.
  VERIFIED.
- **Reversibility: PAIRED** -- `talent/account/linkedin/connect` (+ `verify` if challenged).

## 4.4 `talent/account/gmail/verify` -- POST

**Exactly 1 call site, and it is the OAuth popup callback page**, chunk `2793` @9116.
VERIFIED:

```js
case 0:if(!...includes("?error=gmail_scope_not_granted")){e.n=1;break}
  p({isError:!0,type:"gmail_scope_not_granted"}),
  i&&window.opener.postMessage({type:"GMAIL_CONNECT_ERROR",
    message:"Gmail scope not granted. Please grant all required permissions."},window.location.origin),e.n=4;break;
case 1:return e.p=1,e.n=2,n((0,a.zW)({token:t}));
case 2:p({isError:!1,type:null}),v(!0),
  i?(window.opener.postMessage({type:"GMAIL_CONNECT_SUCCESS"},window.location.origin),
     setTimeout(function(){window.close()},2e3))
   :setTimeout(function(){k("/talent/outreach-agent?gmail=success")},2e3),e.n=4;break;
case 3:e.p=3,s=e.v,console.error("Gmail verification failed:",s),p({isError:!0,type:"verification_failed"}),
  i?window.opener.postMessage({type:"GMAIL_C...
```

- **Body:** `{token}` -- the token lifted from the browser route `/talent/gmail-connect/:token`.
  VERIFIED.
- **This route IS the Gmail "connect" completion.** VERIFIED. It is what closes the OAuth
  loop; see Q1.
- **Reversibility: PAIRED** -- `talent/account/gmail/disconnect`.

## 4.5 `talent/account/gmail/disconnect` -- POST

3 genuine call sites (`app.js` @3684005, `app.js` @4482535, `8379` @26976). The apparent
fourth hit in chunk `1248` is the cross-module key collision documented above and is NOT this
route. VERIFIED:

```js
case 0:return e.p=0,_e("happy_agent_gmail_disconnect_attempted"),e.n=1,S((0,i.vA)({disconnect_reason:t}));
case 1:"success"===(...r.data.status)?(Q(null),l.oR.success("Gmail account disconnected successfully!"),
  _e("happy_agent_gmail_disconnected"),m&&m()):(l.oR.error(...||"Something went wrong. Please try again."),...
```

- **Body:** `{disconnect_reason}`. VERIFIED.
- **Response read:** `res.data.status === "success"`. VERIFIED.
- **Reversibility: PAIRED** -- reconnect via the OAuth popup, completed by `gmail/verify`.

## 4.6 `talent/account/gmail/inbox/send` -- ZERO CALL SITES

**This route is defined and never called.** VERIFIED as a complete negative search over all
86 files (13.4 MB):

- The route string occurs exactly **once**, in the constant declaration
  (`et=o+"talent/account/gmail/inbox/send"`, `app.js` @6927299).
- It is re-exported under the key `zVW` (`zVW:()=>et`).
- `zVW` occurs **0 times** as a property access (`X.zVW`) anywhere in the bundle.

There is no service thunk, no verb, no body and no response shape to report, because no code
touches it. **Reversibility: UNKNOWN**, for the stated reason that nothing exercises it.

INFERRED: this is the send-an-email-from-the-connected-Gmail-inbox endpoint that the outreach
agent would use server-side, exposed in the shared endpoint module but never invoked from the
browser -- the agent sends on the user's behalf from the backend. This matches the product
copy ("our Happpy Agent will reach out to these contacts on your behalf"). The inference is
consistent but unverifiable from the bundle.

**This is the second dead route in the endpoint module.** The other is
`talent/account/analytics` (export `oi`, GET, zero callers), already recorded in
`2026-08-21-uplers-bundle-callsites.md` section 19. A client should not build against either.

## 4.7 `talent/account/outreach-agent` -- POST (adjacent, in scope by prefix)

1 call site, `app.js` @6912163. VERIFIED:

```js
case 0:return e.p=0,
  t=h(h(h({hr_id:d,source:p,why_good_fit:T,is_tailored:!!m},m?{html:m}:{}),v?{linkedin_message_id:v}:{}),P?{gmail_message_id:P}:{}),
  e.n=1,(0,a.rz)(t)(F);
case 1:"redirect"===(n=e.v).data.status?(D(j),z("Please connect your Gmail and LinkedIn accounts to use the Happpy Agent."))
  :"success"===n.data.status?(F((0,a.dg)()),D(_),z((n.data.message||"Your referral request has been submitted successfully")
    +" with ".concat(m?"tailored":"profile"," resume")))
  :(r=n.data.message||"Something went wrong. Please try again.",...)
```

- **Body:** `{hr_id, source, why_good_fit, is_tailored}` always, plus conditional `html`
  (when a tailored resume exists), `linkedin_message_id`, `gmail_message_id`. VERIFIED.
- **Response read:** a **three-valued** `res.data.status`: `"redirect"` (accounts not
  connected), `"success"`, or anything else as an error. VERIFIED. This is the only route in
  the surface with a `"redirect"` status.
- **Reversibility: ONE-WAY.** This submits the referral request. No withdraw route exists,
  consistent with the platform-wide finding that Uplers ships no un-apply anywhere.

---

# 5. Q2 -- `talent/outreach/store-message-template`

**Answers, up front:**

- **Body keys:** two shapes, depending on which of the **two export keys** is used, and on
  the channel. Gmail bodies carry `message_subject`, LinkedIn bodies do not (in the preview
  path) or send it empty (in the thunk path).
- **One channel or both at once: ONE CHANNEL PER REQUEST.** VERIFIED, both paths.
- **Does writing the LinkedIn template require re-sending the Gmail template? NO.** VERIFIED.
  The two POSTs are pushed independently onto a promise array, each behind its own
  changed-and-connected guard, and either can fire alone.

## The route has TWO export keys pointing at the same URL

This is unusual and worth flagging before the call sites, because a naive
one-key-per-route resolver will miss half the call sites. VERIFIED -- module 81935 declares
the same URL twice under two different locals:

```js
nt=o+"talent/outreach/store-message-template",   // @6927375, re-exported as uM3
vn=o+"talent/outreach/store-message-template",   // @6930197, re-exported as kZJ
```

`uM3` (3 call sites incl. the thunk) and `kZJ` (2 call sites) are distinct keys resolving to
the identical string. Total shipped call sites across both: **8**.

## Path A -- `kZJ`, the preview screen (app.js module 75329)

The decisive quote, `app.js` @5389171. This is the whole guard-and-dispatch block; note
`t.push(...)` twice into one array, each independently guarded:

```js
case 0:if(me&&localStorage.setItem(Q,"true"),Te(!0),e.p=1,t=[],
  wt&&null!=ye&&ye.gmail_connected&&t.push({provider:ie,promise:(0,f.o$)(p.kZJ,{
    provider:ie,
    message_template:ye.gmail_template.message,
    message_subject:null!==(n=ye.gmail_template.subject)&&void 0!==n?n:"",
    tag:"rewrite-message-from-preview"})}),
  _t&&null!=ye&&ye.linkedin_connected&&t.push({provider:oe,promise:(0,f.o$)(p.kZJ,{
    provider:oe,
    message_template:ye.linkedin_template.message,
    tag:"rewrite-message-from-preview"})}),
  r={},!t.length){e.n=10;break}
  return e.n=2,Promise.all(t.map(function(e){var t=e.provider;
    return e.promise.then(function(e){return{provider:t,res:e}})}));
...
case 5:c===ie?r.gmail_message_id=u:c===oe&&(r.linkedin_message_id=u);
```

The two guards, declared immediately above at @5389040 -- VERIFIED:

```js
wt=!(!et.gmail||null==ye||!ye.gmail_template
     ||ye.gmail_template.message===et.gmail.message&&ye.gmail_template.subject===et.gmail.subject),
_t=!!et.linkedin&&!(null==ye||!ye.linkedin_template)&&ye.linkedin_template.message!==et.linkedin.message,
kt=wt||_t,
```

**This is the direct answer to "does writing linkedin require re-sending gmail".** `wt` is
"the Gmail template differs from the baseline" and `_t` is "the LinkedIn template differs".
They are independent booleans. If only `_t` is true, `t` contains exactly one entry -- the
LinkedIn POST -- and no Gmail body is sent at all. VERIFIED.

- **Gmail body:** `{provider:2, message_template, message_subject, tag:"rewrite-message-from-preview"}`
- **LinkedIn body:** `{provider:1, message_template, tag:"rewrite-message-from-preview"}`
  -- **no `message_subject` key at all**, not an empty one. VERIFIED.
- **Response read:** `res.data.template_id`, demuxed by provider into
  `{gmail_message_id, linkedin_message_id}` which are then handed to the next step
  (`auto-run-request` / `account/outreach-agent`, both of which accept exactly those two
  optional keys -- see 3.13 and 4.7). VERIFIED. That is the seam that ties this route to the
  send.

## Path B -- `uM3` / thunk `Xv`, the template editor

Thunk (`app.js` @1607052), body is the bare parameter `e` -- UNRESOLVED at the thunk:

```js
bt=function(e){return function(t){return t({type:a.rQ,payload:!0}),new Promise(function(n,r){
  (0,i.o$)(o.uM3,e).then(function(e){n(e)}).finally(function(){return t({type:a.rQ,payload:!1})})})}}
```

Traced to **6 callers**, all single-channel, all three keys. VERIFIED:

```js
// chunk 5422 @84856 -- per-channel save, channel chosen by the argument `a`
n={message_template:t.body||"",message_subject:t.subject||"",provider:a},...,b((0,c.Xv)(n));
// ... o||m.oR.success(a===ia?"Gmail template saved":"LinkedIn template saved")

// chunks 6277 @32668, 7619 @89437, 983 @60779, 8379 @10286 -- "Manage templates" editor
t={message_template:A.message_template||"",message_subject:A.title||"",provider:k},...,f((0,a.Xv)(t));

// chunk 8379 @8594 -- gmail auto-seed, with the provider as a LITERAL
var i={provider:2,message_template:o.message_template,message_subject:o.title||o.message_subject||""};
e((0,s.Xv)(i)).then(...)
```

- **Body:** `{message_template, message_subject, provider}` -- exactly 3 keys, **no `tag`**.
  VERIFIED. The `tag` key exists only on Path A.
- **One channel per call**, `provider` picked by the active tab. The success toast at
  `5422` names the single channel it saved: `a===ia?"Gmail template saved":"LinkedIn template saved"`.
  VERIFIED.
- **Response read:** `res.data.status === "success"` (Path B) vs `res.data.template_id`
  (Path A) -- the same route, read two different ways by two different screens. VERIFIED.
- **Reversibility: IDEMPOTENT-SETTINGS.** The read-back is **`GET talent/outreach/get-message-templates`**
  (export `qfY`, thunk `it` at `app.js` @1603387, no params). VERIFIED. Read it first and the
  prior template text is recoverable; there is no delete-template route.

---

# 6. Q3 -- `POST talent/outreach/settings/followup`

**Answers, up front:**

- **Full body key list: 9 keys, all sent on every write.**
- **A partial body is NOT sent by this client -- the whole record goes every time.** VERIFIED.
  Whether the *server* would accept a partial body is not decidable from the bundle and I did
  not test it.
- **There is no `...spread` of prior state at the POST.** The body is an explicit 9-key object
  literal, each value read individually off the form-state object `R`. The prior state reaches
  the body only because `R` was seeded wholesale by the GET on mount.

## The call site, quoted in full

Chunk `748` @15521 (byte-parallel twin at `9071`; chunk `8379` @52156 holds the GET arm of the
same route). VERIFIED verbatim:

```js
case 4:return V(!0),t=function(e){return e>0?e:1},e.p=5,e.n=6,
  (0,r.o$)("".concat(i.H$l,"talent/outreach/settings/followup"),{
    disabled_followup_gmail:R.disabled_followup_gmail,
    disabled_followup_linkedin:R.disabled_followup_linkedin,
    interval_days:t(R.interval_days),
    interval_days_gmail:t(R.interval_days_gmail),
    interval_days_linkedin:t(R.interval_days_linkedin),
    channel:"both",
    message:R.message||null,
    message_gmail:R.message_gmail||null,
    message_linkedin:R.message_linkedin||null});
case 6:200===(null==(u=e.v)||null===(l=u.data)||void 0===l?void 0:l.status)&&null!=u&&null!==(s=u.data)&&void 0!==s&&s.data
  ?(k=u.data.data,N=function(e){return e>0?e:1},M({
      disabled_followup_gmail:null!==(c=k.disabled_followup_gmail)&&void 0!==c&&c,
      disabled_followup_linkedin:null!==(d=k.disabled_followup_linkedin)&&void 0!==d&&d,
      interval_days:N(null!==(h=k.interval_days)&&void 0!==h?h:1),
      interval_days_gmail:N(null!==(m=null!==(f=k.interval_days_gmail)&&void 0!==f?f:k.interval_days)&&void 0!==m?m:1),
      interv...
```

## The 9 keys

| key | type | how it is produced |
|---|---|---|
| `disabled_followup_gmail` | bool | straight off form state `R` |
| `disabled_followup_linkedin` | bool | straight off `R` |
| `interval_days` | int >= 1 | clamped by `t=function(e){return e>0?e:1}` |
| `interval_days_gmail` | int >= 1 | same clamp |
| `interval_days_linkedin` | int >= 1 | same clamp |
| `channel` | string | **hardcoded literal `"both"`** at the only call site |
| `message` | string or null | `R.message \|\| null` |
| `message_gmail` | string or null | `R.message_gmail \|\| null` |
| `message_linkedin` | string or null | `R.message_linkedin \|\| null` |

- **`channel` is always `"both"`.** VERIFIED -- it is a literal, never a variable, at the only
  POST call site in the bundle. INFERRED: the server accepts other values (why else have the
  key), but this build never sends one, so `"gmail"` / `"linkedin"` are guesses and are NOT
  claimed here.
- **The `interval_days` clamp is client-side only.** `t(e) = e>0 ? e : 1`. VERIFIED.

## Whole record vs partial

The body is a flat 9-key literal with no spread. Every key is present on every call,
including keys the user did not touch, because they are read off `R` -- the single form-state
object that the mount-time GET populated. VERIFIED.

So the *effective* behaviour is "send the whole record", and the mechanism is
seed-then-resend, not spread-prior-state. A client that POSTs a subset would be exercising a
path this UI never exercises.

## Validation gates that run before the POST

VERIFIED verbatim, and load-bearing for anyone building against this route -- the messages
must contain two template variables:

```js
case 0:if(n=(R.message_gmail||"").trim(),a=(R.message_linkedin||"").trim(),
  R.disabled_followup_gmail||""===n){e.n=2;break}
  if(n.includes("{{outreachEmployee}}")){e.n=1;break}
  return o.oR.error("Gmail: The follow-up message must include the {{outreachEmployee}} variable."),e.a(2);
case 1:if(n.includes("{{jobTitle}}")){e.n=2;break}
  return o.oR.error("Gmail: The follow-up message must include the {{jobTitle}} variable."),e.a(2);
case 2:if(R.disabled_followup_linkedin||""===a){e.n=4;break}
  if(a.includes("{{outreachEmployee}}")){e.n=3;break}
  return o.oR.error("LinkedIn: The follow-up message must include the {{outreachEmployee}} variable."),e.a(2);
case 3:if(a.includes("{{jobTitle}}")){e.n=4;break}
  return o.oR.error("LinkedIn: The follow-up message must include the {{jobTitle}} variable."),e.a(2);
```

Each channel's message must contain both `{{outreachEmployee}}` and `{{jobTitle}}`, unless
that channel is disabled or its message is empty. VERIFIED.

## Reversibility

**IDEMPOTENT-SETTINGS.** The read-back is **`GET talent/outreach/settings/followup`** -- same
URL, no params -- at chunk `748` @10953 and chunk `8379` @52156. VERIFIED:

```js
case 0:return G(!0),e.p=1,e.n=2,(0,r.Yr)("".concat(i.H$l,"talent/outreach/settings/followup"));
case 2:200===(...t.data.status)&&null!=t&&...t.data.data&&(x=t.data.data,k=function(e){return e>0?e:1},
  M({disabled_followup_gmail:null!==(l=null!==(s=x.disabled_followup_gmail)&&void 0!==s?s:x.disabled_followup)&&void 0!==l&&l,
     disabled_followup_linkedin:null!==(u=null!==(c=x.disabled_followup_linkedin)&&void 0!==c?c:x.disabled_followup)&&void 0!==u&&u,
     interval_days:k(null!==(d=x.interval_days)&&void 0!==d?d:1),
     interval_days_gmail:k(null!==(h=null!==(m=x.interval_days_gmail)&&void 0!==m?m:x.interval_days)&&void 0!==h?h:1),
     interval_days_linkedin:...
```

The GET's `.data.data` is fed to `M`, the same setter the POST response feeds. **So the exact
prior record is recoverable by reading before writing**, which is what makes this
IDEMPOTENT-SETTINGS rather than ONE-WAY.

One legacy-compat detail worth copying, VERIFIED: the GET falls back from
`disabled_followup_gmail` / `disabled_followup_linkedin` to a **singular legacy field
`disabled_followup`**, and from `interval_days_gmail` / `interval_days_linkedin` to
`interval_days`. The server may return the older single-channel shape. The POST never sends
`disabled_followup` (singular).

---

# 7. Q1 -- there is no `talent/account/gmail/connect`, and here is what replaces it

**Confirmed: no `talent/account/gmail/connect` exists.** VERIFIED by exhaustive grep of route
strings across all 86 files -- the `talent/account/` family is exactly:
`status`, `analytics`, `linkedin/connect`, `linkedin/verify`, `linkedin/disconnect`,
`gmail/verify`, `gmail/disconnect`, `gmail/inbox/send`, `outreach-agent`. No `gmail/connect`.

**What the Gmail connect flow actually uses: a server-side OAuth redirect opened in a popup,
on the web origin, NOT under `/api/`.**

## Step 1 -- the popup

`window.open` to `https://platform.uplers.com/auth/login/gmail/{talent.enc_id}`. **6
occurrences** across `app.js`, chunk `2793` and chunk `8379`. VERIFIED verbatim (`app.js`,
the Happpy Agent connect card):

```js
onClick:je(function(e){null!=e&&e.preventDefault&&e.preventDefault();null==n||n.plan;
  var t="".concat("https://platform.uplers.com","/auth/login/gmail/").concat(null==M?void 0:M.enc_id),
    r=window.open(t,"Gmail OAuth","width=600,height=700,scrollbars=yes,resizable=yes,left="
      +(window.screen.width/2-300)+",top="+(window.screen.height/2-350));
  if(_e("happy_agent_gmail_connect_attempted"),!r)
    return l.oR.error("Please allow popups for this site to connect Gmail"),void _e("happy_agent_gmail_popup_blocked");
```

Note the base is the **bare origin**, not the API base -- `"https://platform.uplers.com"` +
`"/auth/login/gmail/"`, with no `api/` segment. That is exactly why it does not appear in a
`talent/account/` route grep. The path parameter is the talent's `enc_id`.

Two of the six occurrences are a plain anchor rather than a popup (chunk `2793`, the
fallback/retry screen) -- VERIFIED:

```js
(0,s.jsxs)("a",{href:"".concat("https://platform.uplers.com","/auth/login/gmail/").concat(null==l?void 0:l.enc_id),...
```

## Step 2 -- completion detection, two mechanisms in parallel

VERIFIED, third call site (chunk `8379`), which runs both a `postMessage` listener and a
500 ms polling loop over the popup's URL, plus a timeout:

```js
window.addEventListener("message",l),
n=setInterval(function(){try{
  if(e.closed)return void s("Gmail connection was cancelled.");
  var t=e.location.href;
  t.includes("gmail=success")?(e.close(),a()):t.includes("error=")&&(e.close(),s("Gmail connection failed."))
}catch(e){}},500),
o=setTimeout(function(){e.closed||e.close(),s("Connection timed out. Please t...
```

## Step 3 -- the redirect target IS a React Router page, and it calls `gmail/verify`

The route `/talent/gmail-connect/:token` exists exactly once in the bundle as a router path.
Its component is chunk `2793`, and that component is the **only** caller of
`talent/account/gmail/verify`. VERIFIED (chunk `2793` @9116, quoted in full in 4.4):

```js
case 1:return e.p=1,e.n=2,n((0,a.zW)({token:t}));      // POST talent/account/gmail/verify {token}
case 2:p({isError:!1,type:null}),v(!0),
  i?(window.opener.postMessage({type:"GMAIL_CONNECT_SUCCESS"},window.location.origin),
     setTimeout(function(){window.close()},2e3))
   :setTimeout(function(){k("/talent/outreach-agent?gmail=success")},2e3),
```

It also handles the scope-refusal case explicitly, VERIFIED:

```js
if(!...includes("?error=gmail_scope_not_granted")){...}
p({isError:!0,type:"gmail_scope_not_granted"}),
i&&window.opener.postMessage({type:"GMAIL_CONNECT_ERROR",
  message:"Gmail scope not granted. Please grant all required permissions."},window.location.origin),
```

## Step 4 -- the opener re-reads status

On success the parent calls `(0,i.WU)()` = **GET `talent/account/status`** and reads
`res.data.data.gmail`. VERIFIED:

```js
S((0,i.WU)()).then(function(e){var t,n,r;
  Q(...e.data.data.gmail),l.oR.success("Gmail account connected successfully!"),
  localStorage.setItem("outreach_account_connected","true"),_e("happy_agent_gmail_connected"),Fe(),
  2==(...e.data.data.gmail.status)&&(...
```

## The asymmetry, stated plainly

| | LinkedIn | Gmail |
|---|---|---|
| connect initiation | **`POST /api/talent/account/linkedin/connect`** with `{email, password}` | **`window.open("https://platform.uplers.com/auth/login/gmail/{enc_id}")`** -- a top-level OAuth redirect, no API route, not under `/api/` |
| challenge step | `POST .../linkedin/verify` with `{email, code}` | none client-side (Google handles it) |
| completion | the connect/verify response itself (`data.status === 2`) | **`POST /api/talent/account/gmail/verify`** with `{token}`, fired by the callback page `/talent/gmail-connect/:token` |
| completion signalled to opener | n/a (same window) | `window.postMessage({type:"GMAIL_CONNECT_SUCCESS"})` + URL polling for `gmail=success` |
| disconnect | `POST .../linkedin/disconnect` `{disconnect_reason}` | `POST .../gmail/disconnect` `{disconnect_reason}` |

**The finding:** the naming is asymmetric because the *mechanisms* are asymmetric.
`gmail/verify` is not the LinkedIn-style "verify a 2FA code" route its name suggests -- it is
the **OAuth token-exchange completion**, and it is the true counterpart of
`linkedin/connect`. There is no `gmail/connect` because the connect step is a browser
navigation, not an XHR. Meanwhile **LinkedIn has no OAuth at all in this product: the user's
LinkedIn email and password are POSTed to Uplers' own API** (section 4.1, VERIFIED). That is
the substantive half of the asymmetry, and it is worth carrying into any decision about what
this MCP server should or should not automate.

INFERRED (strong, not verified): a client cannot perform the Gmail connect headlessly through
the API surface at all. It would have to drive `https://platform.uplers.com/auth/login/gmail/{enc_id}`
in a real browser through Google's consent screen and let the callback page POST the token.
The only API-reachable Gmail operations are `verify` (which needs a token only the OAuth
redirect produces) and `disconnect`.

---

# 8. Dead code and other things a builder should not trust

| item | status | basis |
|---|---|---|
| `talent/account/gmail/inbox/send` | **ZERO call sites.** Declared, exported as `zVW`, never referenced. | VERIFIED, complete negative search over 86 files |
| `talent/account/analytics` | **ZERO call sites** (prior finding, re-confirmed here) | VERIFIED |
| `store-recommended-jobs` `jobs` key | Always `[]`, at all 8 call sites | VERIFIED |
| `settings/followup` `channel` key | Always the literal `"both"`; other values are unattested | VERIFIED (literal), other values NOT claimed |
| `disconnect` routes' empty-body branch | `null!=e?e:{}` makes a bodyless call legal; no shipped caller uses it | VERIFIED |
| `store-message-template` two export keys | `uM3` and `kZJ` are the same URL; a one-key resolver misses call sites | VERIFIED |
| Status-envelope inconsistency | `res.data.status` is variously numeric `200`, numeric `1`/`2`, or the string `"success"`, and `store-employee-requests` accepts **either** `200` or `"success"` | VERIFIED |

---

# 9. What remains UNMEASURABLE by static analysis

None of these should be settled by guessing, and none should be settled by performing a write.

1. **Whether any of these routes accepts a partial body.** The bundle shows only what this UI
   sends. For `settings/followup` specifically, the UI always sends all 9 keys (section 6).
2. **Whether `POST store-message-template` is an upsert or an insert.** Path A reads back a
   `template_id`, which is consistent with either. No delete-template route exists to
   disambiguate.
3. **Whether `update-tailor-resume` has a read-back** in the `talent/tailor/*` family. Out of
   this slice's scope; this is why it is classified UNKNOWN rather than guessed (section 3.32).
4. **What `talent/account/gmail/inbox/send` does.** Zero client code touches it.
5. **Whether `interview-feedback` overwrites on a repeat POST for the same `company_id`.** The
   client patches its local row either way.
6. **Whether the `settings/followup` `channel` key accepts values other than `"both"`.**
7. **Whether `rewrite-message` / `refine-message` persist anything server-side.** The client
   writes their results only into React state, but a server-side draft or a metering counter
   would be invisible here.
8. **Every response body's true contents.** Only the fields the client destructures are
   knowable. A route may return more.
