# Slice: opaque / account-scoped tokens, ahead of make-public

Scope: everything with **no recognisable personal shape**. Names, emails, phones and
LinkedIn slugs belong to the shape-based identity census and are deliberately NOT
re-measured here.

Authority: the mirror clone of the PUBLISHED remote, walked with `git rev-list --objects
--all`. **62 commits, 463 blobs, 149 blobs at HEAD, 124 binary/undecodable skipped.**
Working tree is clean and identical to the mirror tip (`54876ae`), so "HEAD" below means
"currently served by the remote" and not merely "in the working copy".

Instrument: `scripts/publish_opaque_scan.py` (this pass MEASURES; nothing was scrubbed,
nothing was committed, no file outside the scanner and this report was touched).

## THE OUTPUT RULE OBSERVED

No value appears anywhere in this document. Every value is written as
`sha256(value)[:8]`, called a HANDLE, which is enough to tell two values apart and to
prove the same value appears under two keys, and is not enough to address anything.

---

## HEADLINE

| | count |
|---|---|
| distinct live-handle tokens, **HIS** | **113** |
| distinct live-handle tokens, **THIRD-PARTY** | **29** |
| total distinct | **142** |
| currently-valid credentials (bearer / session / JWT / presigned) | **0 account credentials**; see FLAG-1 |

**Highest severity: `$.talent_details.enc_id` - `alnum(32)`, 1 distinct, at HEAD.**
His Uplers profile handle. It is not merely account-scoped, it is proven live *by this
repo's own code*, which is what separates it from the 87 other opaque strings around it.

**FLAG-1, raised per the stop-rule and left for the lead to rule on:** 80 distinct
UNEXPIRED signed URLs are present at HEAD (`media.licdn.com`, expiry parameters dated
2026-09-03 and 2026-09-10, i.e. in the future as of 2026-08-24). They are **company logo
images**, so what the signature buys a stranger is a public marketing image and not
access to an account. I did not treat this as a work-stopping credential find for that
reason, but it meets the literal description "unexpired presigned URL" and is reported
here without being printed. Details in FINDING-7.

---

## INVENTORY

Ownership column: **HIS** = addresses the operator's own Uplers account or one of his own
profile rows. **3P** = addresses another human. **JOB/CAT** = addresses a requisition, a
company or a catalog row, i.e. nobody.

### Account-scoped opaque handles (the target class)

| json path | shape | occ | distinct | live handle? | whose | where |
|---|---|---|---|---|---|---|
| `$.talent_details.enc_id` | alnum(32) | 1 | 1 | **YES - proven, see F1** | HIS | HEAD |
| `$.talent.enc_id` | alnum(32) | 2 | 1 (same value) | **YES** | HIS | HEAD+HIST |
| `$.talent_details.skills[i].enc_id` | alnum(32) | 61 | 61 | probable | HIS | HEAD |
| `$.talent_details.primaryskills[i].enc_id` | alnum(32) | 56 | 56 (subset of the 61) | probable | HIS | HEAD |
| `$.talent_details.tools[i].enc_id` | alnum(32) | 12 | 12 | probable | HIS | HEAD |
| `$.talent_details.achievements[i].enc_id` | alnum(32) | 8 | 8 | probable | HIS | HEAD |
| `$.talent_details.experiences[i].enc_id` | alnum(32) | 3 | 3 | probable | HIS | HEAD |
| `$.talent_details.projects[i].enc_id` | alnum(32) | 2 | 2 | probable | HIS | HEAD |
| `$.talent_details.educations[i].enc_id` | alnum(32) | 1 | 1 | probable | HIS | HEAD |
| `$.talent_details.enc_id_nda` / `$.talent.enc_id_nda` | alnum(32) | 3 | 1 | probable | HIS | HEAD+HIST |
| `$.talent_details.enc_id_org` / `$.talent.enc_id_org` | alnum(32) | 3 | 1 | probable | HIS | HEAD+HIST |
| `$.hrs.data[i].enc_id` | alnum(32) | 12 | 4 | probable | HIS | HEAD |
| `$.hrs.data[i].current_talent_hr.enc_id` | alnum(32) | 2 | 2 | probable | HIS | HEAD |
| `$.data.gmail.enc_id` | alnum(32) | 1 | 1 | probable | HIS | HEAD |

Subtotal, distinct opaque handles that are HIS: **97**.

### Numeric account ids (opaque by having no shape at all)

| json path (representative) | shape | occ | distinct | live handle? | whose | where |
|---|---|---|---|---|---|---|
| `talent_id` across 13 paths | digits(7) | 210 | **1** | **YES - see F2** | HIS | HEAD+HIST |
| `$.talent_details.user_id`, `$.talent.user_id` | digits(7) | 3 | **1** | probable | HIS | HEAD+HIST |
| `$.data.rows[i].outreach_employee_id` | digits(6) | 21 | **7** | probable | **3P** | HEAD+HIST |
| `$.data.rows[i].talent_gmail_email_id` | digits(6) | 14 | 7 | probable | HIS-side | HEAD+HIST |
| `created_by` / `published_by` / `closed_by` / `ta_id` | digits(4-7) | 42 | **20** | probable | **3P** | HEAD |

### Conversation handles

| json path | shape | occ | distinct | live handle? | whose | where |
|---|---|---|---|---|---|---|
| `$.data.rows[i].gmail_thread_id` | alnum_dash(17) | 14 | 7 | **YES - see F5** | HIS mailbox | HEAD+HIST |
| `$.data.rows[i].talent_linkedin_message_id` | null | 7 | 0 | n/a | - | HEAD |

### Handles hidden inside URLs (no key names them)

| json path | shape | occ | distinct | live handle? | whose | where |
|---|---|---|---|---|---|---|
| `$.detail.JDURL`, `$.detail.jd_path`, and the same two under `$.hrs.data[i].hr.detail` | url(131), `ouid=` param | 4 | **2** | probable | **3P** (Google) | HEAD |
| `company_logo` (25 loci) | url(175-225), `e=`+`t=` | 80 | 80 | **UNEXPIRED** | company | HEAD |

### Present, opaque, and NOT identity (recorded so the next pass does not re-litigate)

| json path | shape | distinct | why it is not a finding |
|---|---|---|---|
| `$.enc_id`, `$.hrs.data[i].hr.enc_id` | alnum(32) | 6, 9 | requisition handles; the requisition is fetchable unauthenticated by `HR_Number` |
| `$.data.list[i].hr_enc_id` | alnum(32) | 46 | same - requisition, not person |
| `strong_proficiencyskills[i].enc_id` | alnum(32) | 46 + 15 | rows of a REQUISITION's skill list |
| `$.data[i].enc_id` | alnum(32) | 25 | 20 are company-catalog rows in `outreach_settings_companies.json`; remainder are job rows |
| `$.masters.skills[i].enc_id`, `$.masters.tools[i].enc_id` | alnum(32) | 1, 1 | global catalog rows |
| `$.assessments[i].enc_id`, `$.hrs.data[i].ai_data.master_enc_id` | alnum(32) | 1 | ONE assessment-template handle shared across 5 job fixtures - a catalog id, not a person |
| `HR_Number` | alnum(14-18) | 54 | the public requisition string; `MANIFEST.md` documents the endpoint as public and unauthenticated |
| `hr_id`, `outreach_hr_id` | digits(4-6) | 65, 48 | requisition ids in two different id spaces (measured: zero overlap between them) |
| `id`, `skill_id`, `city_id`, `job_function_id` etc. | digits(1-8) | many | catalog rows; admitted at TRIVIAL tier and not carried forward |

---

## FINDINGS

### F1 - `$.talent_details.enc_id`: his profile handle, and the repo proves it is live

**Shape:** `alnum(32)`. 1 occurrence at `$.talent_details.enc_id` in
`tests/fixtures/talent_profile.json`, plus 2 more of the SAME value at
`$.talent.enc_id` in `tests/fixtures/talent_preference.json` (verified identical by
handle, not by eye). At HEAD.

**This is the target class exactly.** A 32-character mixed alphanumeric string under a key
that reads like an encoding artefact. No shape scanner flags it. Nothing about it looks
personal.

**Question 1, is it a live handle - answered YES, and not by inference.** The repo's own
source settles it:

- `uplers_server/resume_write.py:199` defines `talent_enc_id()`, whose docstring reads
  *"His own `talent_enc_id`, the ONLY parameter the download route takes. MEASURED at
  `talent_details.enc_id` in the captured profile response."*
- `uplers_server/resume_write.py:818` and `:922` then call
  `client.get_json(EP_DOWNLOAD_RESUME, {"talent_id": identifier})` with that value, where
  `EP_DOWNLOAD_RESUME = "talent/talent-download-resume-profile"`.

So the published fixture contains the exact string that this published code sends to
Uplers to **download his resume**. Whether the vendor also requires a session cookie is
not something this repo can answer, and the safe reading is that it may not - the route
takes one parameter and that parameter is in the repo.

**Question 2, his or third party - HIS.**

**Test applied:** key name (`enc_id` under `talent_details`) plus call-site tracing. NOT
entropy: entropy cannot distinguish this from the 46 requisition `enc_id`s beside it,
which are harmless.

### F2 - `talent_id`: one value, 210 times, across three fixtures

**Shape:** `digits(7)`. **210 occurrences, exactly 1 distinct value** (handle `c4c78e67`),
spread over 13 distinct json paths in `talent_profile.json`, `talent_preference.json`,
`outreach_tailor_activity.json` and `payment_transactions.json`, including
`$.data.transactions.data[i].talent_id`. At HEAD.

The cardinality IS the finding: a column with 210 rows and one value is not a foreign key
into a catalog, it is the identity of the one account every row belongs to.

**Question 1 - probable live handle.** `talent_id` is the parameter name the resume
download route takes (F1). The value carried under that key here is the seven-digit id
rather than the enc_id, so the two id spaces are not interchangeable, but a seven-digit
account id in a platform whose endpoints take `talent_id` is an addressing handle by
construction, and it is trivially enumerable besides.

**Question 2 - HIS.** I used this value as the ownership oracle for the whole slice: a
row carrying it is his row. That is how `$.talent_details.skills[i].enc_id` (61 handles)
was classified HIS rather than catalog - every one of those 61 rows carries this
`talent_id`, and none of the 61 appears in `$.masters.skills` (measured overlap: 0).

### F3 - `outreach_employee_id` survived a sanitisation that removed everything around it

**This is the sibling repo's failure, reproduced here, and it is the finding I was sent
to look for.**

`tests/fixtures/_specimens/outreach_contact_leak.json` is a deliberately sanitised
specimen. Compared field by field against the live capture it was derived from
(`tests/fixtures/outreach_missed_followups.json`), by handle:

| field in the specimen | distinct | overlap with the live fixture |
|---|---|---|
| `employee_name` | 7 | **0** - substituted |
| `employee_business_email` | 7 | **0** - substituted |
| `contact_value` | 7 | **0** - substituted |
| `outreach_employee_id` | 7 | **7 of 7 - KEPT VERBATIM** |

Every field with a recognisable personal shape was replaced. The one field with no shape
at all was not. The specimen therefore still names the same seven real people as the
unsanitised fixture, by their platform id.

**Question 1 - probable live handle.** `uplers_server/endpoints.py:493-494` records two
routes taking `?outreach_hr_id=`; the employee id is the same subsystem's row key for a
person. Both probes returned 404, so I cannot claim a working route, only a stable id.

**Question 2 - THIRD PARTY, 7 people.** This is the severe ownership case: these are not
the operator's ids to publish, and consent was never his to give.
`MANIFEST.md` (lines 233-237) already records that this fixture family carries "8 distinct
real addresses" of real people, which independently confirms the underlying rows are live
captures rather than synthetic.

### F4 - `created_by` / `published_by` / `closed_by` / `ta_id`: 20 staff accounts

**Shape:** `digits(4-7)`, **20 distinct** after discarding the `0`/`1` sentinels. At HEAD.

No published identifier list contains "`_by` columns", which is why they are here. An
audit-trail column is not metadata: its value is a **user of the platform**, and on a
staff-operated talent board that user is an Uplers employee.

Two pieces of evidence that these are one id space naming humans, not per-table counters:

1. One handle appears under `created_by`, `published_by` **and** `ta_id`. `ta_id` is the
   Talent Acquisition contact - a person. Same value, three roles, therefore one person.
2. Three further handles appear under both `created_by` and `published_by`.

They share the seven-digit shape with his own `user_id` and `talent_id` (F2), which is
consistent with a single platform-wide user table.

**Caution recorded:** `acceptance_by` and `self_applied_by` hold only `0` and `1` -
booleans wearing an id's name. I caught this because `sha256("0")` and `sha256("1")` are
recognisable; a scanner that reported "11 occurrences of an actor id" there would have
been reporting a flag. Those are classified TRIVIAL and excluded from the 20.

### F5 - `gmail_thread_id` and `talent_gmail_email_id`

**Shapes:** `alnum_dash(17)`, 7 distinct; and `digits(6)`, 7 distinct. Both at
`$.data.rows[i].*` in `outreach_missed_followups.json`. HEAD **and** history.

A Gmail thread id addresses a conversation inside **his mailbox**. It is not a credential
- reading the thread still needs his Google session - but it is a stable, permanent handle
to a specific private conversation with a named outside person, and it is the kind of
value that is only ever useful to someone who already has partial access. Measured: the
`talent_gmail_email_id` set and the `outreach_employee_id` set do not overlap (0 of 7), so
they are two different id spaces, not one column duplicated.

`talent_linkedin_message_id` is present with 7 occurrences and is **null in all 7** - the
key exists, the value never did.

### F6 - `ouid=` inside a Google Docs job-description link

**Shape:** `url(131)` carrying an `ouid=` query parameter. 4 occurrences, **2 distinct**
Google account handles, at `$.detail.JDURL`, `$.detail.jd_path` and the same pair nested
under `$.hrs.data[i].hr.detail`. At HEAD.

`ouid` is Google's obfuscated account id for the signed-in user who produced the share
link. No key in this repo is named for it; it rides inside an ordinary-looking document
URL under keys called `JDURL` and `jd_path`. **This is the same failure mode as F3 one
level deeper:** the value has no shape, and it is not even under a key - it is inside a
string that a reviewer classifies as "a link to the JD" and moves on.

**Question 2 - THIRD PARTY** (whoever at Uplers shared the document).

My scanner did not catch this on its first pass. See CONTROL below.

### F7 (FLAG-1) - 80 unexpired signed URLs

**Shape:** `url(175-225)` on `media.licdn.com`, carrying `e=` (expiry), `v=` and a
43-character `t=` token. **80 occurrences, 80 distinct**, at `$.data[i].company_logo`
(24 length-variants) and `$.hrs.data[i].hr.company.company_logo`. At HEAD.

Expiry values decode to **2026-09-03 and 2026-09-10** - both in the future as of
2026-08-24, so these are **not expired**.

Stated plainly because the stop-rule asks for it: these are live signed URLs sitting in a
repo about to go public. Stated equally plainly: the object each one signs is a
**company's logo image**, already public on LinkedIn. There is no account, no document and
no personal file behind the signature. I am flagging it rather than deciding it.

### F8 - real live values copied into prose and tests

Three 32-character values that appear in a fixture ALSO appear hard-coded elsewhere. I
tested every 32-char literal in every `.md` and `.py` against the set of 243 live fixture
values:

| file | handle | what it is | verdict |
|---|---|---|---|
| `_audit/_slices/_slice-account-surface-capture.md` | `f3dcb998` | `$.data.gmail.enc_id` - **his Gmail-integration record** | **real, HIS, in a prose document** |
| `tests/test_assessments.py` | `653b6daa` | the shared assessment-template `enc_id` | real, catalog, harmless |
| `tests/test_talent_shape.py` | `af1bfdee` | `$.enc_id` of a requisition | real, job, harmless |

The first one is the pattern the brief warned about - an account-scoped handle written
into a document *about* the capture. Three other 32-char literals
(`tests/test_outreach.py`, `tests/test_path_hygiene.py`, `scripts/leak_matrix.py`) matched
NO fixture value and are synthetic constants.

### F9 - history-only residue

Only one class is history-only rather than at HEAD: `lowerhex(40)` literals in
`_audit/2026-08-23-uplers-auth-slice.md` (9 occurrences, 3 distinct) that do **not**
resolve as objects in this repo. They are git-sha-shaped strings from somewhere else.
Not identity; recorded for completeness, and recorded because the discriminator used was
"ask the object database", not "it looks like a sha".

---

## NEGATIVE SPACE

Account-ish keys and credential shapes I searched for **across all 62 commits** and found
**ZERO** of. This list is the value of the pass being negative: it is what a future reader
does not have to re-check.

**Keys with zero occurrences anywhere in history:**
`profileId`, `profile_id`, `candidate_id`, `member_id`, `account_id`, `subscriber_id`,
`person_id`, `recruiter_id`, `conversation_id`, `resource_uri`, `csrf_token`,
`refresh_token`, `id_token`, `session_token`, `sessionId`, `auth_token`, `api_key`,
`apikey`, `x-api-key`, `client_secret`, `private_key`, `aws_secret`, `Set-Cookie`.

**Credential VALUES: zero.** Specifically checked and cleared:

- **JWTs.** 61 grep hits on an `eyJ` prefix, all in `tests/test_session_lifecycle.py` and
  `tests/test_talent_tools.py`. Every one is synthetic: the claim segments base64-decode
  to `{"sub":"talent-identity-must-never-be-printed"}` and
  `{"sub":"decoy-subject-never-stored"}`. Deliberate test fixtures.
- **AWS/GCS presigned signatures.** `X-Amz-Signature`, `X-Amz-Credential` and
  `AWSAccessKeyId` appear only in `scripts/capture_outreach.py` (as the redaction REGEX)
  and `tests/test_capture_gate.py` (its test). No file carries a matching value. This
  independently confirms the claim written at `capture_outreach.py:175-176`.
- **`resumePath.url`** - the presigned S3 URL found in the capture path on 2026-08-24 -
  **is not present in any tracked file, at HEAD or in history.** The key `resumePath` does
  not appear in any fixture. The fix landed before a capture wrote one.
- **Bearer / session values.** 656 grep hits on `Bearer` and 271 on `Authorization:` are
  all header-name mentions in code and prose. Scanning for a long literal adjacent to any
  credential name across the whole tree returned 2 candidates, both zero-digit English:
  a test sentinel string and a test function name.
- `li_at`, `JSESSIONID`, `XSRF-TOKEN` appear as **names in redaction lists only**.

---

## CONTROL

`python scripts/publish_opaque_scan.py --control` builds a throwaway git repo, commits one
synthetic specimen of every shape claimed, runs the **same** scan path over it, and
deletes it. Nothing is planted in this repo.

**13 shapes claimed, 13 detected:** opaque-alnum32, opaque-lowerhex32, uuid36,
gmail-threadish17, account-digits7, thirdparty-digits6, actor-digits7, jwt, bearer-header,
presigned-url, unnamed-key-opaque, signed-url-unlisted-param, account-handle-in-query-param.

**Shapes I could NOT demonstrate detection for: none remain - but two of the thirteen were
added only AFTER the repo scan caught the scanner out, and that sequence is the honest
record:**

1. `signed-url-unlisted-param` - a signed URL whose signature parameter is called `t`
   rather than anything on the enumerated list. **The first mirror pass missed all 80 of
   F7.** Found by a separate hand census of URL query parameters, not by the scanner.
2. `account-handle-in-query-param` - `ouid=` inside an ordinary link. **The first mirror
   pass missed both of F6.**

Both were added as specimens, the control was re-run and **failed (11/13)**, the rule was
then generalised - parse every URL's query string and run the same admission over each
parameter, rather than lengthening a parameter list - and the control re-run **passes
(13/13)**. The scan in this report is from the fixed scanner.

**Mutation test (proving the control can fail at all):** with `entropy()` forced to return
0.0, the control drops to 9/13, losing exactly `opaque-lowerhex32` and
`unnamed-key-opaque` - the two specimens that depend only on the value-only rule. The
other nine survive because a key rule also covers them, which is the intended redundancy.

**Negative controls (values that must NOT be admitted, and are not):** a 3-digit lookup
code, a boolean, English prose, a 3-letter currency slug, a timestamp string.

---

## METHOD NOTES, including where the method was wrong

- **Entropy was a filter, never a decider, and this is not a slogan.** The first run of the
  value-only rule over source text returned roughly 5,900 rows that were Python
  identifiers: `strong_proficiencyskills` is 24 characters with entropy 3.7 and is
  indistinguishable from a real handle by any threshold. Two discriminators fixed it, both
  recorded in the scanner: a word/identifier shape test, and a digit-density floor.
- **Git object ids are decidable, not guessable.** 40-character hex strings are resolved
  against the object database rather than pattern-matched, so a commit reference in a
  document is dismissed on evidence.
- **The `sha256("0")` tell.** Handles make low-cardinality sentinels obvious: `5feceb66`
  and `6b86b273` are `sha256("0")` and `sha256("1")`. Four keys that look like actor ids
  (`acceptance_by`, `self_applied_by`, and some `client_id` / `created_by` rows) hold only
  those. Reporting them as ids would have inflated F4 by 11 occurrences.
- **Two id spaces can share a name.** `hr_id` and `outreach_hr_id` are both `digits(6)`,
  both appear in the same row of `outreach_tailor_activity.json`, and have **zero value
  overlap** across 65 and 48 distinct values. `endpoints.IDENTIFIER_SPACES` documents a
  third: `id`, `enc_id` and `HR_Number` all get sent to the API *as* `hr_id` by different
  routes. Any scrub that treats "`hr_id`" as one thing will be wrong somewhere.
- **What I could not settle.** Whether Uplers' routes accept these handles without a valid
  session. That needs a live unauthenticated probe against the vendor, which is out of
  scope for a measuring pass. Every "live handle" verdict above except F1 is therefore
  written as *probable*, and F1 is written as proven only because this repo's own code
  demonstrates the call.


---

## REDACTOR COVERAGE

Added 2026-08-24, after the two censuses. This section describes the INSTRUMENT
only. **Nothing here has been applied to a fixture** - the redaction runs at
CAPTURE time, so every count below is what a re-derivation will do, measured by
running the extended redactor over all 42 committed fixtures into a scratch
directory. No fixture was modified and nothing was committed.

Home: `scripts/capture_outreach.py`. The three capture scripts that already
imported its `write_fixture` inherit every rule automatically; the two that did
not now do - see NOT-COVERED note 6 for why that was the load-bearing half.

### Covered, and how

| # | Class | Treatment | Keys / rule | Values a re-derivation changes |
|---|---|---|---|---|
| 1 | PROSE, deletable | **DROP** | `message_full`, `reply_summary`, `company_pitch`, `tech_stack_details`, `frontend_message`, `prerequisites` | 77 |
| 1b | PROSE, not deletable | **CONDEMN** | `description`, `about`, `JobDescription`, `title` - a sign-off or NANP number in one DELETES the fixture | n/a (gate) |
| 2 | Opaque handles | **REPLACE** | `enc_id`, `enc_id_nda`, `enc_id_org`, `TalentEncId`, `talent_id`, `user_id`, `talent_gmail_email_id`, `gmail_thread_id` | 531 |
| 2b | Third-party handles | **REPLACE** | `outreach_employee_id`, `created_by`, `published_by`, `closed_by`, `ta_id` | 40 |
| 3 | Handles inside URLs | **REPLACE** | every query parameter of every bare URL, admitted by SHAPE not by name | 96 |
| 4 | SIGNOFF-NAME | **CONDEMN** | positional shape, both real line breaks and the `\r\n` escaped form | n/a (gate) |
| 4b | PHONE-NANP | **CONDEMN** | `NNN-NNN-NNNN` with token boundaries | n/a (gate) |
| 5 | NAME-NEAR-ROLE at HEAD | **DROP** | all three live findings sit in `company_pitch`; located by recomputing the census's own sha256 handles, so no value was read | 19 (subset of row 1) |

Rows 1 and 5 overlap, and the 49 pre-existing MASK substitutions are not
listed. Totals over the 42 fixtures: **90 values deleted, 716 values replaced, and the
leak detector then reports the whole corpus CLEAN.**

Cross-checks against this document, none of them arranged: `talent_id` = 210
occurrences (F2), `company_logo` signature params = 80 (F7), `ouid=` = 4 across
`JDURL` and `jd_path` (F6), `gmail_thread_id` = 7 and `talent_gmail_email_id` =
7 (F5), actor ids = 26 replaced out of 42 occurrences, the balance being the
`0`/`1` sentinels and nulls this document warned about (F4).

### DROP versus REPLACE, stated as a rule

**DROP when nothing reads the field.** Prose cannot be pattern-scrubbed - a
regex over free text is a much weaker guarantee than a key delete, and the
2026-08-24 leak is the proof: every shaped field in that file was correctly
substituted and four people still leaked through two prose fields. Deleting the
key needs no enumeration of what a signature block can contain.

**REPLACE when a test needs the shape.** A fixture exists to pin the shape the
vendor really sends. Deleting `enc_id` from 380 rows or `talent_id` from 210
would break the round-trip the files are for, so the key survives and the value
is destroyed: same length, same alphabet, separators kept in position, an `int`
still an `int` of the same width. The substitute is a salted SHA-256 keystream
keyed on the VALUE, so the same original maps to the same replacement in every
file and referential integrity survives. The mapping is ONE-WAY and no table
exists anywhere - a reversible substitution plus its key is precisely the
de-anonymisation artefact `test_pii_hygiene` forbids.

### Controls - each watched RED before it was watched green

22 controls added to `tests/test_capture_gate.py`. The pre-change scripts were
restored from `HEAD` and the new controls run against them:

**19 of 22 FAILED against the old redactor and pass against the new one.** The
3 that did not are labelled `__GUARD` rather than `__CONTROL`, following this
file's existing convention: they are over-reach guards (an ordinary query
string, a `0`/`1` sentinel, benign prose) and by construction cannot fail
against code that does less.

Two controls initially passed against the OLD code and were therefore certifying
nothing - a referential-integrity check that equality satisfies trivially when
nothing is substituted, and a round-trip check that a redactor doing nothing
also passes. Both were strengthened until they went red, and the reason is
written into each. That sequence is the honest record: **the first draft of this
control set contained two checks that could not fail.**

Suite: **1426 passing before, 1448 after.** No existing test changed.

### The blocklist law - NOT violated

Measured rather than asserted: every value under an identifier-shaped key in
every fixture was collected, and every tracked non-fixture file was scanned for
those exact strings.

- `tests/test_pii_hygiene.py` names **0** real fixture values. Its blocklists
  (`SYNTHETIC_SLUGS`, `SYNTHETIC_LINKEDIN_IDS`) are empty, and
  `CLASSIC_TEST_NUMBERS` / `STUB_EMAIL_DOMAINS` hold only values that belong to
  nobody. The guard hunts by shape and allowlists the synthetic, so it never had
  to name what it forbids.
- `scripts/capture_outreach.py` names **0**.

**No untracked blocklist file was needed and none was created.** One unrelated
untracked file is now supported and gitignored: `scripts/.redaction_salt`, an
optional override for the substitution salt. The tracked default salt is
deliberately not a secret, but a published salt leaves the SHORT digit-shaped
handles recoverable by brute force - a seven-digit account id has only 10^7
candidates. For `alnum(32)` this is irrelevant; for `talent_id`, `user_id`,
`outreach_employee_id` and the actor ids the tracked salt buys obfuscation
rather than destruction. Dropping one line of text at that path before a
re-derivation closes it. **Recommend doing so.**

### NOT covered, and why

1. **`description`, `about`, `JobDescription`, `title`.** Body-shaped, and each
   has a live reader (`shaping.html_to_text`, `talent_shape`, `agent_surface`)
   plus live assertions. Deleting them empties the surfaces the fixtures exist
   to pin. Covered as a GATE instead: a sign-off block or a NANP number in one
   deletes the fixture and asks a human. **A name with no sign-off and no role
   word beside it still passes.**
2. **`job_description` cannot be dropped even though nothing reads it.**
   `normal_key` folds `job_description` and `JobDescription` onto one entry, so
   listing either deletes both - and `JobDescription` is 36 values with a live
   reader. The case-folding that closed the camelCase `resumePath` defect is the
   same folding that makes these one field; it cannot be had one way only.
   Found by simulating the redaction and reading which keys vanished, not by
   inspection.
3. **`discard_reason` and `objective`.** Prose-shaped and excluded: the first is
   platform-canned text asserted non-empty on every row, the second is his own
   profile summary, asserted truthy. Neither is correspondence.
4. **`HR_Number`, `hr_enc_id`, `hr_id`, `outreach_hr_id`, catalog `id`s.** Ruled
   non-identity by this document and left alone. `HR_Number` in particular is
   hard-coded in 22 places across the server and the suite.
5. **History.** The redactor governs the next capture. Six of the nine
   human-readable findings are invisible at HEAD and live only in two commits;
   no capture-time rule reaches them. Only a history rewrite or not publishing
   does, and it must be verified against a MIRROR of the remote.
6. **A surprise worth recording: two capture scripts were bypassing the shared
   redaction entirely.** `capture_talent_rows.py` (owner of `talent_feed.json`
   and `talent_pipeline.json` - all three findings live at HEAD) and
   `capture_profile_fixture.py` (owner of `talent_profile.json` - the one handle
   PROVEN live) each carried their own `strip()`: an exact-name key delete with
   no case folding, no mask layer, no credential-URL rule and no value rule of
   any kind. Two redactions of different strength is not redundancy, it is a
   hole with a second copy of the rules in front of it. Both now compose the
   shared `redact()` after their own `strip()`, and both now run `contact_leaks`
   before leaving a file on disk. Without this the highest-severity finding in
   each census would have been uncovered by everything above.

### Re-derivation fallout the lead should expect

Two tests hard-code a real value that the new REPLACE layer will change, both
enumerated by handle rather than by value:

| file | handle | what it is |
|---|---|---|
| `tests/test_assessments.py:128` | `653b6daa` | the shared assessment-template `enc_id` |
| `tests/test_talent_shape.py:229` | `af1bfdee` | a requisition `enc_id` |

Both are the catalog handles this document rules harmless, and both break only
because `enc_id` is replaced UNIFORMLY by key name. A path-aware carve-out would
spare them, and it is not offered here: deciding that a requisition handle is
safe is this document's call, not the redactor's, and the carve-out would also
miss the per-row handles the same key name carries.

One further consequence, which is a design question rather than a defect:
`tests/test_outreach.py:903` asserts that every key in
`outreach.WITHHELD_CONTACT_KEYS` is present and truthy in the raw fixture row,
and `message_full` is one of them. Once the capture stops recording it, that
assertion has nothing to stand on. The check exists to prove the withholding is
MEANINGFUL - that the payload really carries the field and the shaper really
declines to print it. If the fixture no longer carries it, the proof has to
change shape. **Flagged, not changed.**
