# Slice: consent semantics (static analysis of the Uplers platform bundle)

Method: read-only static analysis of the public JS bundle. No authenticated request, no
POST/DELETE against any Uplers API, no `mcp__uplers__*` call. Only HTTP GET on
`https://platform.uplers.com/build/...` static assets.

## Bundle provenance

| artifact | value |
|---|---|
| `app.js` | 7,935,093 bytes -- IDENTICAL to the 2026-08-22 record |
| `Last-Modified` | `Fri, 21 Aug 2026 13:17:17 GMT` |
| `ETag` | `"791475-6598e749df140"` |
| lazy chunks | 85 chunks, 5,476,711 bytes total -- IDENTICAL to the 2026-08-22 record |
| local copy | `D:\claude-workspace\uplers-bundle\` (`app.js`, `chunks\`, `chunkmap.json`, `urls.txt`) |

Nothing changed since the 2026-08-22 measurement. Code is minified but NOT obfuscated:
identifiers are mangled, string literals and property names survive intact, so field names,
route strings and JSX class names are all directly greppable.

### Symbol resolution table (used throughout; each row VERIFIED by grep in `app.js`)

API-route module (`H$l` = base URL `o`):

| export | local | URL |
|---|---|---|
| `I_D` | `ut` | `talent/outreach/get-outreach-dashboard-data` |
| `MRd` | `vt` | `talent/outreach/recommended-jobs-meta-email` |
| `WmL` | `xt` | `talent/outreach/recommended-jobs-email` |
| `Xkg` | `wt` | `talent/outreach/consent-email-job-scan` |
| `YfT` | `pt` | `talent/outreach/consent-auto-run` |
| `Zgu` | `ot` | `talent/outreach/outreach-step` |
| `aP`  | `_t` | `talent/outreach/store-recommended-jobs` |
| `Tsc` | `kt` | `talent/outreach/auto-run-request` |

HTTP helpers (`app.js` @7352308, @7352582, @7353018):

| export | body | verb |
|---|---|---|
| `Yr` (`A`) | `r.A.get(e)` | GET, URL only |
| `o$` (`E`) | `r.A.post(t,n,{headers:s})` | POST, url + body |
| `rn` (`P`) | `r.A.delete(e)` | DELETE, URL only, **no body, no params** |

Redux thunks (actions module):

| export | local | what it does |
|---|---|---|
| `oF` | `pt` | GET `get-outreach-dashboard-data` -> stores whole `.data.data` as `state.happpyAgent.dashboardData` |
| `rq` | `ut` | GET `outreach-step` -> maps `plan`, `plan_end_date`, `has_plan_expired`, `conversion_offer`, `credit_*`, `step1.gmail_connected`, `step1.linkedin_connected`, plus `raw` |
| `bX` | `gt` | POST `store-recommended-jobs` with the caller's body |
| `CA` | `ht` | pure redux write: `dashboardData.auto_run_consent = !!e` (+ localStorage) |

Screens (by `<title>`):

| chunk | screen |
|---|---|
| `1625` | Dashboard \| Happpy Agent |
| `2063` | Interview Companies \| Happpy Agent |
| `3474` | Recommended jobs \| Happpy Agent (owns the Gmail-scan tab) |
| `6069` | Dashboard \| Happpy Agent (interview widget) |
| `6734` | My activity \| Happpy Agent |
| `8379` | Configure \| Happpy Agent (owns the auto-run toggle) |

---

# VERDICT

**TWO DIFFERENT CONSENTS, MIS-PAIRED.** The hypothesis holds. There is no disagreement to
resolve, because `get-outreach-dashboard-data -> consent_email_job_scan` and
`interview-list -> meta.has_consent` are not the same flag and are not even read by the same
part of the product.

Three findings carry the verdict, in descending order of strength:

1. **VERIFIED -- `interview-list`'s `meta` is dead to the UI.** All four copies of the
   `interview-list` hook in the bundle destructure only `response.data.data` (the companies
   array). The hook's entire return value is
   `{companies, loading, submittingFeedback, feedbackError, submitFeedback, clearFeedbackError}`.
   `meta` is never stored, never returned, never rendered. `meta.has_consent`,
   `meta.consent_interview_email_scan` and `meta.gmail_connected` are unconsumed by the shipped
   frontend. Whatever `interview-list.meta.has_consent: false` means, it governs nothing the
   platform's own UI does.

2. **VERIFIED -- `consent_interview_email_scan` appears ZERO times in the entire bundle**
   (`app.js` + all 85 chunks). It is a server field with no client reader at all.

3. **VERIFIED -- the interview email-scan consent UI is designed but NOT SHIPPED.** Chunk `6734`
   ships a complete CSS block for it -- `.aa-interview__consent`, `--active`, `--skeleton`,
   `-checkbox`, `-check-wrap`, `-enable-btn`, `-revoke-btn`, `-email`, `-footer`, plus an
   `.aa-interview__error--consent` state and a dedicated `consent` grid-area in the
   `.aa-interview` layout. **All 26 occurrences of `aa-interview__consent*` fall inside the CSS
   string of module `16625` (offsets 85295-89061, module bounds 84800-105600). Zero JSX anywhere
   in the bundle references any of them** (`grep 'className:"aa-interview__consent'` -> no
   matches, in any file). An interview-scan consent panel with an enable button, a revoke button
   and an acknowledgement checkbox was styled and laid out; the React component that renders it
   is absent from the shipped build.

Taken together: the backend has an interview-email-scan consent (`meta.has_consent` +
`meta.consent_interview_email_scan` on `interview-list`), the CSS for its UI is already
deployed, and the component is still to come. Meanwhile the job-board-email-scan consent
(`consent_email_job_scan` / `recommended-jobs-meta-email -> has_consent`) is fully shipped and
live. The account's `true` and `false` are two different questions, correctly answered.

**Practical consequence for the operator's account:** `interview-list.meta.has_consent: false`
is NOT evidence that his Gmail job-board scan consent is off. It is (INFERRED) the interview
scan, which is not grantable from the UI yet. His job-scan consent reads `true`, and the route
the platform itself re-reads after a job-scan write is `recommended-jobs-meta-email`.

---

# Evidence per question

## Q1 -- Where does the UI READ each field?

### `consent_email_job_scan` -- 3 occurrences, ALL in chunk `3474`, and 2 of them are WRITES

| offset | site | nature |
|---|---|---|
| `3474` @96174, @96214 | enable handler `Ar` | WRITE into local state from the POST response |
| `3474` @97284 | disable handler `Or` | WRITE `null` into local state |

Plus one READ site in a different screen, chunk `1625` (Dashboard), inside its own GET of
`get-outreach-dashboard-data`:

```js
r=(a?.data?.data)||{},
... U(r.agent_pref_fields_submitted), $(!!r.consent_email_job_scan), X(!!r.has_submitted_happpy_feedback), ae(!0)
```

`$` is the setter of `q=Ue((0,a.useState)(!0),2),J=q[0],$=q[1]`. The state `J` has exactly one
read in that scope (`3474`-style enumeration of the bare identifier `J` gave 15 hits; 11 belong
to other component scopes; the two in this scope are the same expression):

```js
Et=(0,a.useMemo)(function(){return ne&&!J},[ne,J]),
...
Et&&e.push({id:"email-scan", label:Tt.setupLabel, ctaLabel:"CHECK IT OUT", required:!1,
  onClick:function(){return t("/talent/job-agent/recommended-jobs?tab=gmail-scan")}})
```

with `Tt = {title:"Enable Email Scan", description:"Let Happpy Agent find jobs from your inbox
and recommend referral-ready opportunities automatically", ...}`.

**So the ONLY read of `consent_email_job_scan` in the product is a dashboard setup-checklist
nudge that fires when the flag is false and links to `/talent/job-agent/recommended-jobs?tab=gmail-scan`.**
It is a pointer, not a state display. VERIFIED.

Note also (VERIFIED): in chunk `3474`, `consent_email_job_scan` is written into the local meta
state `Oe` but the enumerated set of properties ever READ off `Oe` is
`{best_for_you_breakdown, best_for_you_count, breakdown, gmail_connected, gmail_email,
has_consent, job_function_name, last_job_scan, total_jobs}` -- `consent_email_job_scan` is not
among them. The field is copied into state and then never consulted.

### `has_consent` -- 18 occurrences, ALL in chunk `3474`, ZERO anywhere else

16 reads, 2 writes. Every read is `Oe.has_consent`, where `Oe` is the state populated by:

```js
Sr = useCallback(async ({silent}={}) => { ... await (0,c.Yr)(s.MRd); ... Ee(Z(n)||null) ... })
// s.MRd = talent/outreach/recommended-jobs-meta-email
// function Z(e){var r=e?.data; return r&&200===r.status&&void 0!==r.data ? r.data : null}
```

So on the Recommended-jobs screen, `has_consent` comes from **`recommended-jobs-meta-email`**,
NOT from `interview-list`. The 16 reads gate, in order of appearance:

- the polling loop that waits for the first scan to complete (@93850, @94186, @94819, @95628, @95792)
- the revoke guard `Or` (@97107) and the revoke-modal opener `Er` (@98035)
- the "scanning your Gmail" progress state `Qr` (@102020), the empty state `Kr` (@102303)
- the filter row `wa()` (@105382, @105571)
- the tab-count badge (@119990)
- **the consent panel's visibility (@120983)** -- `Oe.has_consent ? null : (Oe.gmail_connected ? <consent panel> : <connect-gmail panel>)`
- the whole Gmail-scan layout (@124117), the summary aside (@125271), the fallback list (@126756)

### `consent_interview_email_scan` -- ZERO occurrences

VERIFIED across `app.js` and all 85 chunks.

### Does any toggle/switch bind its CHECKED state to one of them?

**NO -- for the email-job-scan consent. VERIFIED.** The only checkbox on the consent panel is:

```js
(0,b.jsx)("input",{id:"hra-rec-gmail-consent",className:"hra-rec__consent-checkbox",
  type:"checkbox",checked:er,onChange:function(e){return rr(e.target.checked)}})
```

and `er` is `Xe=N((0,n.useState)(!1),2),er=Xe[0],rr=Xe[1]` -- a purely local acknowledgement
flag, initialised `false` on every mount, backing the copy "I understand and allow Happpy Agent
to scan my job board alert emails only for the purpose of job recommendations." It is the
arming gate for the Enable button (`disabled:!er||We`), not a state display.

`has_consent` instead controls **which panel exists at all**: when it is false the consent
panel renders, when true the panel is replaced by the active-scan layout plus a "Remove consent"
button. That is a stronger binding than a checkbox, not a weaker one -- the platform routes the
entire screen off `recommended-jobs-meta-email -> has_consent`.

**YES -- for the auto-run consent.** See Q4.

## Q2 -- Are `has_consent` and `consent_email_job_scan` the same underlying flag?

**They are the same CONSENT (the Gmail job-board email scan), surfaced under two names on two
different routes. INFERRED, on four independent pieces of evidence:**

1. **Same component holds both, in one state object.** The enable handler writes them together
   (chunk `3474` @96159):

   ```js
   Ee(function(e){return M(M({},e||{}),{},{
     has_consent:!0,
     consent_email_job_scan: n?.consent_email_job_scan,
     gmail_email: n?.gmail_email ?? e?.gmail_email,
     last_job_scan:null, total_jobs:0})})
   ```

   and the disable handler clears them together (@97269):

   ```js
   Ee(function(e){return M(M({},e||{}),{},{
     has_consent:!1, consent_email_job_scan:null,
     gmail_connected: a?.gmail_connected ?? e?.gmail_connected,
     gmail_email: a?.gmail_email ?? e?.gmail_email})})
   ```

   A single `POST talent/outreach/consent-email-job-scan` sets BOTH to their granted values; a
   single `DELETE` on the same route clears BOTH. That is one write acting on one flag.

2. **The dashboard nudge keyed on `consent_email_job_scan` navigates to the screen governed by
   `has_consent`.** `!consent_email_job_scan` -> "Enable Email Scan / CHECK IT OUT" ->
   `/talent/job-agent/recommended-jobs?tab=gmail-scan` -> the `!has_consent` consent panel.
   The product treats the dashboard flag being false and the scan screen's consent panel showing
   as the same condition.

3. **Both share the same copy and the same subject.** Dashboard: "Let Happpy Agent find jobs
   from your inbox". Scan screen: "Allow Gmail job board scan ... We strictly only read alerts
   from job boards." Success toast: "We will scan job board emails from LinkedIn, Naukri,
   Glassdoor, and Indeed only."

4. **No evidence against.** They never co-occur in a conflicting condition, and nothing gates a
   different screen on one versus the other.

**But `interview-list.meta.has_consent` is a DIFFERENT flag from `recommended-jobs-meta-email
-> has_consent`, despite the identical name.** INFERRED, on the structural parallel:

| route | generic field | specific field | shared field |
|---|---|---|---|
| `recommended-jobs-meta-email` | `has_consent` | `consent_email_job_scan` | `gmail_connected`, `gmail_email` |
| `interview-list` (`meta`) | `has_consent` | `consent_interview_email_scan` | `gmail_connected` |

Two outreach meta payloads with the same shape convention: `has_consent` = "the consent this
route cares about", plus a specifically-named companion. On the job route the companion is the
JOB scan; on the interview route it is the INTERVIEW scan. Under this reading
`interview-list.meta.has_consent: false` and `consent_interview_email_scan: null` agree with
each other (interview scan not granted, never set), and neither contradicts
`consent_email_job_scan: true` (job scan granted).

This is INFERRED and not VERIFIED, because the bundle never reads `interview-list.meta` at all
-- there is no client code whose behaviour could disambiguate the two `has_consent` fields. What
IS verified is that no UI behaviour depends on `interview-list.meta.has_consent`, so it cannot
be authoritative for anything the platform does.

## Q3 -- What do POST and DELETE on `talent/outreach/consent-email-job-scan` do?

**Exactly 2 call sites, both in chunk `3474`, both on the Recommended-jobs Gmail-scan tab.**
`grep '[A-Za-z]\.Xkg'` across `app.js` + all 85 chunks returns exactly those two. This matches
the recorded inventory's "2 call sites".

### POST -- ENABLE

```js
Ar = async function(){
  if (er && !We) { ... } else return;              // requires the local ack checkbox + not busy
  qe(!0); U("");
  a = await (0,c.o$)(s.Xkg,{});                    // POST consent-email-job-scan, body {}
  n = Z(a);
  Ee(state => ({...state, has_consent:!0, consent_email_job_scan:n?.consent_email_job_scan,
                gmail_email:n?.gmail_email ?? state?.gmail_email,
                last_job_scan:null, total_jobs:0}));
  t = await Sr();                                  // REFETCH recommended-jobs-meta-email
  if ((t?.total_jobs ?? 0) > 0 || t?.last_job_scan != null) await Mr();  // then the jobs list
  Pr("success","We will scan job board emails from LinkedIn, Naukri, Glassdoor, and Indeed only.",
     {title:"Gmail scan enabled"});
}
```

- **Trigger:** the "Enable Gmail Scan" button (`className:"hra-rec__enable-btn"`, `onClick:Ar`,
  `disabled:!er||We`, label `We?"Enabling...":"Enable Gmail Scan"`), inside the "Allow Gmail job
  board scan" panel. Only reachable when `!has_consent && gmail_connected`.
- **Body genuinely empty:** yes -- the literal `{}` is passed as the axios POST body. VERIFIED.
- **Query string / path parameter:** none. `s.Xkg` is the bare concatenated URL; the POST helper
  `E` appends only headers (Authorization + utm_*). VERIFIED.
- **Refetch after:** `Sr()` = **GET `talent/outreach/recommended-jobs-meta-email`**, then
  conditionally `Mr()` = GET `recommended-jobs-email?best_for_you=...`. VERIFIED.

### DELETE -- REVOKE

```js
Or = async function(){
  if (!Je && Oe?.has_consent) { ... } else return; // requires current consent = true
  Qe(!0); U("");
  r = await (0,c.rn)(s.Xkg);                       // DELETE consent-email-job-scan, no body
  a = Z(r);
  Ee(state => ({...state, has_consent:!1, consent_email_job_scan:null,
                gmail_connected:a?.gmail_connected ?? state?.gmail_connected,
                gmail_email:a?.gmail_email ?? state?.gmail_email}));
  Ge([]); dr(null); tr("all"); lr(!1); rr(!1); _e(1); $e(!1);
  Pr("success","Happpy Agent will no longer scan your job board alert emails.",
     {title:"Gmail scan consent removed"});
}
```

- **Trigger:** "Remove consent" button (`className:"hra-rec__revoke-btn hra-rec__revoke-btn--inbox"`,
  `onClick:Er`) in the active-scan summary aside -> `Er` opens a confirm modal
  (`Er=function(){!Je&&Oe?.has_consent&&$e(!0)}`) -> the modal's danger button fires `Or`.
  Modal copy: title "Remove Gmail scan consent?", body "Happpy Agent will stop scanning job
  board alert emails (<gmail_email>). You can enable Gmail scan again at any time.", buttons
  "Cancel" / "Remove consent". Wired at
  `(0,b.jsx)(ee,{open:Ke,gmailEmail:Oe?.gmail_email,revoking:Je,onClose:...,onConfirm:Or})`.
- **Body genuinely empty:** the DELETE helper is `r.A.delete(e)` -- it takes only a URL. No body
  is sent at all, and no config object. VERIFIED.
- **Query string / path parameter:** none. VERIFIED.
- **Refetch after:** **NONE.** `Or` updates local state optimistically, clears the job list, and
  stops. Unlike the POST path it does not call `Sr()`. VERIFIED.

### The decisive refetch target

**`talent/outreach/recommended-jobs-meta-email` is the route the UI re-reads after enabling.**
`grep '[A-Za-z]\.MRd'` returns exactly one call site in the whole bundle -- `Sr`, the GET that
both bootstraps the screen and is awaited immediately after the POST. By the brief's own
criterion, **`recommended-jobs-meta-email -> has_consent` is the authoritative read-back for the
email-job-scan consent.**

Note the asymmetry: **nothing refetches `get-outreach-dashboard-data` after either write.** The
dashboard's `consent_email_job_scan` is refreshed only when the Dashboard screen mounts. It is a
downstream copy, one render cycle behind at best.

### Correction to the recorded route inventory

The inventory recorded the response as "none read". **That is wrong.** Both responses ARE read,
through `Z(e) = e.data.status===200 ? e.data.data : null`:

- POST response -> `consent_email_job_scan`, `gmail_email`
- DELETE response -> `gmail_connected`, `gmail_email`

Whether the server actually populates those keys is not decidable from the bundle -- the client
uses `?.` and falls back to prior state for `gmail_email`/`gmail_connected`, so a bare
`{status:200,data:{}}` would not break it. But the client does read them, and the inventory
line should be corrected.

## Q4 -- The auto-run pair

### `auto_run` is WRITE-ONLY. VERIFIED exhaustively.

Every occurrence of `auto_run` (excluding `auto_run_consent`) in `app.js` + all 85 chunks --
**8 in total, enumerated by regex, no exceptions** -- is the same outbound payload field:

| file | offset | code |
|---|---|---|
| `app.js` | 4525448 | `l((0,k.bX)({jobs:[],auto_run:p===xp,outreach_mode:p}))` |
| `chunks/6277` | 4521 | `p((0,a.bX)({jobs:[],auto_run:"auto"===g,outreach_mode:g}))` |
| `chunks/6277` | 5102 | `p((0,a.bX)({jobs:[],auto_run:"auto"===t,outreach_mode:t}))` |
| `chunks/7619` | 4521 | `p((0,i.bX)({jobs:[],auto_run:"auto"===j,outreach_mode:j}))` |
| `chunks/7619` | 5102 | `p((0,i.bX)({jobs:[],auto_run:"auto"===t,outreach_mode:t}))` |
| `chunks/8379` | 83790 | `n((0,s.bX)({jobs:[],auto_run:t===Xe,outreach_mode:t}))` |
| `chunks/983`  | 4527 | `p((0,i.bX)({jobs:[],auto_run:"auto"===j,outreach_mode:j}))` |
| `chunks/983`  | 5108 | `p((0,i.bX)({jobs:[],auto_run:"auto"===r,outreach_mode:r}))` |

**There is not one read of `auto_run` anywhere in the bundle.** It is derived on write from the
Manual/Auto mode selector (`auto_run = (mode === "auto")`) and posted alongside `outreach_mode`.
The UI reads back `outreach_mode`, never `auto_run` -- e.g. `useEffect(...,[t?.outreach_mode])`
in `983`/`6277`/`7619`.

`bX` posts to **`talent/outreach/store-recommended-jobs`** (`gt = (t)=>{...(0,i.o$)(o.aP,e)...}`,
`aP -> _t -> "talent/outreach/store-recommended-jobs"`), **not** to `outreach-step`. And the
`outreach-step` GET thunk maps only `plan`, `plan_end_date`, `has_plan_expired`,
`conversion_offer`, `credit_plan`, `credit_left`, `credit_added`, `step1.gmail_connected`,
`step1.linkedin_connected`, plus `raw` -- `auto_run` survives only inside `raw`, which nothing
destructures for it.

So `outreach-step -> auto_run: 1` is a server echo of a mode write. It is a *mode* fact
("outreach_mode is auto"), not a *consent* fact.

### `auto_run_consent` IS the toggle's checked state. VERIFIED.

`auto_run_consent` has exactly 3 occurrences in the bundle -- 1 write, 2 reads:

**The toggle** (chunk `8379`, Configure screen, `?tab=auto-run`):

```js
t = (0,o.d4)(function(e){var t; return !(e.happpyAgent.dashboardData?.auto_run_consent === undefined
                                         || !e.happpyAgent.dashboardData.auto_run_consent)}),
[l,h] = useState(t);
useEffect(function(){ h(t) },[t]);
...
(0,f.jsx)("input",{type:"checkbox",className:"hc-run-check__input",
  checked:l, disabled:b, onChange:function(e){return _(e.target.checked)}})
```

Label: "Let Happpy Agent find and apply to relevant jobs on my behalf after 2 days of
inactivity" / "Agent will find matching jobs and apply without asking for approval each time."
Card header: "Auto run HAPPPY".

`state.happpyAgent.dashboardData` is set wholesale from `response.data.data` of
**`get-outreach-dashboard-data`** (thunk `oF`/`pt`). So the toggle's `checked` binds, through a
one-line local mirror, to **`get-outreach-dashboard-data -> data.auto_run_consent`.** This is
the toggle-checked binding the brief asked for, and it is unambiguous.

**The nudge** (chunk `3474` @89420) is the mirror of the job-scan nudge:

```js
f = useSelector(e => !!e.happpyAgent.dashboardData?.auto_run_consent),
m = useSelector(e => e.happpyAgent.dashboardPreferencesLoaded),
...
!m||f ? null : <Link className="hra-rec__auto-run-nudge" to="/talent/job-agent/configure?tab=auto-run">
                 "Want HAPPPY to auto run on jobs if you are inactive?" </Link>
```

Loaded and not consented -> show the nudge, linking to the screen that owns the toggle. Exactly
the pattern the job-scan consent uses.

**What `consent-auto-run` writes** (chunk `8379`, the only call site of `u.YfT` in the bundle):

```js
r = l;  h(n);  g(!0);                              // optimistic local flip, keep old value r
o = await (0,p.o$)(u.YfT,{consent:Boolean(n)});    // POST consent-auto-run
if (o?.data?.status === 200) {
  e((0,s.CA)(n));                                  // redux: dashboardData.auto_run_consent = !!n
  c.oR.success("HAPPPY auto run " + (n?"enabled":"disabled"));
} else { h(r); c.oR.error("Failed to update"); }   // roll back on failure
```

`CA` (`ht`) is a pure state writer -- `{...dashboardData, auto_run_consent:!!e}` plus a
localStorage cache write. **No route is refetched after the auto-run POST.** The write path is
optimistic-then-reconciled-from-nothing.

### Answers

- **The auto-run toggle binds to `auto_run_consent`** (from `get-outreach-dashboard-data`), not
  to `auto_run`. VERIFIED.
- **`consent-auto-run` writes `auto_run_consent`.** VERIFIED at the client; the field it writes
  server-side is INFERRED from the fact that the client immediately sets exactly that field and
  a later dashboard fetch is expected to agree.
- **`outreach-step -> auto_run: 1` and `get-outreach-dashboard-data -> auto_run_consent: false`
  are also not the same thing.** `auto_run` is the Manual/Auto *mode* (written via
  `store-recommended-jobs`, read back as `outreach_mode`); `auto_run_consent` is the separate
  "run without asking me, after 2 days of inactivity" *permission*. Same mis-pairing pattern as
  the email-scan pair, and equally non-contradictory: the account is in auto MODE and has not
  granted the inactivity auto-run PERMISSION.
- **Refetch target:** none for `consent-auto-run`. The nearest authoritative read is
  `get-outreach-dashboard-data -> auto_run_consent`, which is the field the toggle displays and
  the field `CA` writes. For the *mode*, the mode-change handler in `8379` calls
  `n((0,s.rq)({silent:!0,force:!0}))` = **GET `outreach-step`** immediately after the write, so
  `outreach-step` is the read-back for `outreach_mode`/`auto_run`.

## Q5 -- Is there a route that READS BACK the email-job-scan consent on its own?

**No route returns only that flag. Two GETs carry it; one is authoritative.**

The complete consent/scan route inventory in the bundle (`grep` for route-form literals
containing `consent` or `scan` across `app.js` + all chunks) is exactly three entries:

| route | verbs used | carries |
|---|---|---|
| `talent/outreach/consent-email-job-scan` | POST, DELETE | write-only |
| `talent/outreach/consent-auto-run` | POST | write-only |
| `talent/outreach/recommended-jobs-meta-email` | GET | `has_consent` + scan metadata |

- **`GET talent/outreach/recommended-jobs-meta-email`** is the read-back. It is a plain GET, no
  parameters, and it is the route `Ar` awaits immediately after the POST. Its `.data.data`
  yields (enumerated from every property the UI reads off it): `has_consent`, `gmail_connected`,
  `gmail_email`, `last_job_scan`, `total_jobs`, `breakdown`, `best_for_you_breakdown`,
  `best_for_you_count`, `job_function_name`. Not flag-only, but it is a read, it is cheap, and
  it is what the platform itself trusts.
- **`GET talent/outreach/get-outreach-dashboard-data`** also carries `consent_email_job_scan`
  (and `auto_run_consent`), but it is a large dashboard aggregate and is never refreshed by
  either consent write.

**Recommendation for the MCP server:** read the email-job-scan consent from
`recommended-jobs-meta-email -> has_consent`, and read the auto-run consent from
`get-outreach-dashboard-data -> auto_run_consent`. Neither requires a write.

---

# What remains UNMEASURABLE by static analysis

Each of these needs a live authenticated observation or a server-side source; none of them
should be settled by guessing, and none should be settled by performing a write.

1. **Whether `interview-list.meta.has_consent` and `recommended-jobs-meta-email.has_consent` are
   backed by the same DB column.** The bundle cannot say: it never reads the former. The
   structural parallel (Q2) is the strongest available argument and it is inference, not
   measurement. A same-column reading would require the two routes to disagree on the same
   account, which is exactly what was observed -- so a same-column reading is *disfavoured*, but
   only a server-side check or a controlled toggle experiment could close it.

2. **What `consent_interview_email_scan: null` means as distinct from `has_consent: false`.**
   Zero client readers, no CSS naming that distinguishes them, no copy. `null` (never set) vs
   `false` (explicitly revoked) is a plausible reading and nothing in the bundle supports or
   refutes it.

3. **Whether the interview email-scan consent is grantable at all right now.** The component is
   absent from the build, and there is no route in the bundle that would write it. If a write
   route exists server-side, it is not referenced by any shipped client code.

4. **The exact response bodies of `POST`/`DELETE consent-email-job-scan`.** The client reads
   `consent_email_job_scan`/`gmail_email` from POST and `gmail_connected`/`gmail_email` from
   DELETE, all optional-chained with fallbacks. Whether the server sends them cannot be
   determined without issuing the call -- which this slice deliberately did not do.

5. **Whether `POST consent-email-job-scan` is idempotent, and what it returns when consent is
   already granted.** The UI can never reach the POST while `has_consent` is true (the button
   only exists inside the `!has_consent` panel), so the bundle documents no such path. An MCP
   server that POSTs blind would be exercising an untested branch.

6. **Whether `DELETE` is safe to probe.** It is not -- it revokes. And the revoke path does not
   refetch, so a client that DELETEd to "read" the flag would leave both the server and any
   open UI in a changed state. Do not use the write routes to determine state.

7. **Whether `get-outreach-dashboard-data` also returns a `has_consent` key.** The thunk stores
   the entire `data.data` object, so the bundle is compatible with it existing; no client code
   reads such a key, so its presence or absence is invisible here. (The Dashboard chunk `1625`
   reads only `consent_email_job_scan` from that payload.)

8. **Server-side coupling of `auto_run` and `auto_run_consent`.** `auto_run` is written via
   `store-recommended-jobs` and echoed by `outreach-step`; `auto_run_consent` is written via
   `consent-auto-run` and echoed by `get-outreach-dashboard-data`. Two write routes, two read
   routes, no client code that relates them. Whether the backend keeps them independent is not
   observable from the bundle.
