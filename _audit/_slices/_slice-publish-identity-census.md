# Publish-gate identity census -- human-readable identity shapes, all 62 commits

Measured 2026-08-24 against a MIRROR of the published remote. This pass
MEASURES. It scrubs nothing and decides nothing; it exists so that a human can
decide with a complete count in front of them.

Scope: the HUMAN-READABLE identity classes. The OPAQUE-TOKEN class (enc_id,
talent_id, user_id, gmail_thread_id, outreach_employee_id, actor ids, session
values, signed URLs) is a SEPARATE census and is deliberately not duplicated
here. See `_slice-publish-opaque-tokens.md`.

## THE OUTPUT RULE THIS FILE OBEYS

No found value appears anywhere below. Not redacted, not truncated, not
first-and-last character. Every finding is addressed by a synthetic label
(`A1`, `B2`) plus a 12-hex SHA-256 prefix handle. This applies equally to the
repository owner's own data.

Rationale, stated because a later reader will be tempted to "just include the
value so we can find it": a value reproduced in an audit report is a fresh copy
of the exact thing the audit exists to remove, and the report outlives the
removal. The previous wave found a real recruiter id written into a runbook AS
THE WORKED EXAMPLE OF WHY YOU MUST NOT DO THAT. The handle is sufficient --
`scripts/publish_identity_census.py --triage` regenerates any value on demand
from the mirror, to stdout, for a human, without writing it down.

Every handle used below was verified by recomputing SHA-256 over the value it
claims to address; 13 of 13 matched, so no label is mis-assigned.

---

## HEADLINE

| | |
|---|---|
| Third-party people (class A), distinct values | **9** |
| ...distinct INDIVIDUALS behind them | **at least 7** |
| ...live at HEAD | **3** |
| ...history-only, invisible at HEAD | **6** |
| Repo owner (class B), distinct values | **3** (+1 in commit metadata) |
| Synthetic (class C), distinct values | **72** |
| Shape collisions, not identity values (class X) | **266** |
| Unclassifiable (`A?`) after adjudication | **0** |
| Shapes returning ZERO across all history | **5** |

**Publishing this repository as it stands publishes the personal data of at
least 7 third-party individuals, 4 of whom are invisible at HEAD and live only
in history.** Nothing in a HEAD-only review can see them.

---

## 1. INSTRUMENT AND POPULATION

- Scanner: `uplers/scripts/publish_identity_census.py`
- Population: `git rev-list --objects --all` in a mirror of the published
  remote, cross-checked against a per-commit `git ls-tree -r --full-tree` walk
  of all 62 commits. The script raises rather than proceeding if a blob reached
  by the tree walk is absent from the object enumeration.
- Binary exclusion: CONTENT SNIFF (NUL byte in the leading 8192 bytes, or under
  85 percent text bytes), never file extension.
- Self-exclusion: the scanner and this report are excluded by path suffix.
- Numeric boundaries: TOKEN boundaries `(?<![A-Za-z0-9_])`, never digit-only.

| Population fact | Count |
|---|---|
| Commits | 62 |
| Blobs total | 339 |
| Blobs excluded as binary (by sniff) | 0 |
| Blobs excluded as the instrument itself | 0 |
| Blobs actually scanned | 339 |
| Bytes scanned | 9,349,461 |
| Distinct paths carrying at least one finding | 71 |
| Distinct findings (shape, value) pairs | 350 |

Every blob in the repository is text. Nothing was skipped.

---

## 2. CONTROL -- shown firing before any result was trusted

A scan that has only ever reported what it happened to find certifies nothing.
Synthetic values, one or more per shape, were planted in a scratch file OUTSIDE
the repository and the scanner was pointed at it. No planted value is real, and
every plant was removed afterwards.

| Shape | Spec check | Reported with plant | Reported after removal |
|---|---|---|---|
| EMAIL | check 1 | 1 | 0 |
| PHONE-IN | check 2 | 2 (see note) | 0 |
| PHONE-E164 | check 2 | 1 | 0 |
| PHONE-NANP | added (see s.4) | 1 | 0 |
| PROFILE-SLUG | check 3 | 1 | 0 |
| LI-COMPANY-ID | check 4 | 1 | 0 |
| LI-MEMBER-TOKEN | check 4 | 1 | 0 |
| LI-URN-ID | check 4 | 1 | 0 |
| CREDENTIAL-JWT | check 5 | 1 | 0 |
| CREDENTIAL-COOKIE | check 5 | 1 | 0 |
| NAME-NEAR-ROLE | extra | 3 | 0 |
| SIGNOFF-NAME | added (see s.4) | 2 | 0 |
| AT-HANDLE | extra | 1 | 0 |
| PERSON-URL | extra | 2 | 0 |

Note on PHONE-IN reporting 2 for 1 plant: the planted 10-digit member URN also
satisfies the Indian-mobile shape. That is the documented false-positive
surface of check 2, not a defect.

The SIGNOFF-NAME plant was made in BOTH forms it occurs in -- a real line break
and the two-character `\r\n` escape inside a JSON string -- and both fired. That
mattered: every real sign-off found in this repository is in the escaped form.

**VERDICT: the control fired for all five spec shapes, both in the presence of a
plant and, at zero, in its absence. There is no shape in this census that has
not been demonstrated failing. No shape is undemonstrated.**

---

## 3. THE HIGHEST-SEVERITY FINDING -- prose fields were never scrubbed

CLASS A. Location: one blob at `tests/fixtures/outreach_missed_followups.json`,
reachable from 2 of the 62 commits, NOT live at HEAD.

This is the file the previous wave believed it had scrubbed, and it did scrub it
-- STRUCTURALLY. All seven `employee_name`, `employee_business_email`,
`employee_linkedin_url`, `contact_display`, `contact_value`, `from_email` and
`to_email` fields are synthetic in both the old and the current blob (a
`Redacted Contact <n>` pattern, reserved `.invalid` domains, and
`/in/redacted-contact-<n>` slugs). A field-by-field diff of the two blobs
confirms this: the LinkedIn URL column is byte-identical across the scrub and
was already synthetic.

**The scrubber walked the STRUCTURED FIELDS and never walked the PROSE.** Two
free-text fields, `message_full` and `reply_summary`, carry quoted reply bodies
with intact email signature blocks. Six class-A values survive there:

| Label | Shape | Handle | Commits | Live at HEAD | Caught by a shape check? |
|---|---|---|---|---|---|
| A4 | NAME-NEAR-ROLE | `72741a3d2243` | 2 | no | yes (as a two-word run) |
| A5 | PHONE-IN | `8108090afa73` | 2 | no | yes |
| A6 | PHONE-NANP | `2b3832ebcdee` | 2 | no | **no** -- shape did not exist |
| A7 | SIGNOFF-NAME | `1974ecc3151e` | 2 | no | **no** -- shape did not exist |
| A8 | SIGNOFF-NAME | `334275e3e104` | 2 | no | **no** -- shape did not exist |
| A9 | SIGNOFF-NAME | `b237797ddef9` | 2 | no | **no** -- shape did not exist |

A4, A6 and A7 are the same individual, captured three ways. Of the seven rows in
this fixture, four leaked identity through prose. One row concentrates the worst
of it: a single signature block carries that person's given name, their job
title, their employer, and their phone number -- while the
`employee_business_email` field one key away had already been rewritten to a
reserved domain.

**THIS IS THE ANSWER TO THE QUESTION I WAS ASKED TO CHECK.** The sibling census
found a specimen where every personally-SHAPED field was substituted and an
unshaped id field stayed real. This is the REVERSE, and it is worse: the shaped
fields were substituted, which is exactly what makes the file read as synthetic
to anyone who opens it, while the same people's names and numbers sit in prose a
few lines below. Nothing about the file's appearance warns a reader. **The scrub
is a decoy.**

STATE AT HEAD: fixed. The current blob replaces every `message_full` and
`reply_summary` with a `Redacted reply body <n>` string, and direct membership
testing confirms the digit runs are absent from the HEAD blob.

STATE IN HISTORY: LIVE. Two commits still carry it, and a mirror clone of the
published remote reproduces it today.

### The three class-A findings that ARE live at HEAD

| Label | Shape | Handle | Path | Commits | Live at HEAD |
|---|---|---|---|---|---|
| A1 | NAME-NEAR-ROLE | `071105dfc4a0` | `tests/fixtures/talent_feed.json` | 39 | **yes** |
| A2 | NAME-NEAR-ROLE | `08c8ccc18879` | `tests/fixtures/talent_feed.json` | 39 | **yes** |
| A3 | NAME-NEAR-ROLE | `8a9a5ff2e349` | `tests/fixtures/talent_pipeline.json` | 39 | **yes** |

These are three named individuals inside captured job-description markdown --
named as a team lead, a founder, and a CEO/CTO respectively, each with a
biographical sentence attached. A mitigating fact the decision-maker should
weigh: this text was published by the platform as a public job advert, so the
association is already public. It is still a named living person's data
travelling into a permanent public repository under this project's name, and it
is decided by a human, not by this census.

A separate cross-check corroborated these three and found no fourth: an
independent NAME-APPOSITIVE pattern (a capitalised run immediately followed by
`CEO`, `CTO`, `Founder`, `VP`, `Head of`, `Director` or `Lead`) returned exactly
2 hits across all 339 blobs, both already on the list above.

---

## 4. WHAT THIS RUN PROVED ABOUT THE INSTRUMENT ITSELF

Four of the nine class-A findings were invisible to every shape check in the
spec. They were found by a human reading a file that all five checks had passed.
The order is recorded deliberately: **the instrument did not find these, a
person did.**

1. **A GIVEN NAME ALONE HAS NO SHAPE.** The name check requires two or more
   titlecase words, so a one-word sign-off matches nothing. The guard spec says
   this outright -- "None of these five detects a personal NAME" -- and this run
   is its demonstration.
2. **NO NANP PHONE SHAPE EXISTED.** Both inherited phone regexes assume an
   Indian mobile or a leading `+`. A US number written `NNN-NNN-NNNN` was
   invisible to both.

Both gaps were closed and the entire history re-scanned:

- `SIGNOFF-NAME` -- a POSITIONAL shape rather than a lexical one: a closing word
  (`Regards`, `Thanks`, `Best`, ...), then a line holding only one or two
  capitalised words. A lone given name offers no other handle. It found 3.
- `PHONE-NANP` -- NANP formatting with token boundaries. It found 1.

Both were shown failing on planted synthetic values before their results were
counted, in both the plain-text and JSON-escaped forms.

**This is why the census is worth more than the guard.** The guard was green on
this repository. Green meant "no shape I know how to look for", and four real
people were outside those shapes.

---

## 5. FULL CLASSIFICATION

Every one of the 350 distinct findings is adjudicated. The `A?` bucket is EMPTY
-- not because nothing was ambiguous, but because each ambiguous item was read
in its file, in context, and assigned.

| Class | Meaning | Distinct values |
|---|---|---|
| **A** | another living person | **9** |
| **B** | the repo owner's own | **3** |
| **C** | synthetic (reserved domain, redacted token, zeroed number) | **72** |
| **X** | shape collision -- matched a detector but is not an identity value | **266** |
| **A?** | could not be classified confidently | **0** |

### Class A, all nine

| Label | Shape | Handle | Path | Commits | Blobs | Occurrences | Live at HEAD |
|---|---|---|---|---|---|---|---|
| A1 | NAME-NEAR-ROLE | `071105dfc4a0` | `tests/fixtures/talent_feed.json` | 39 | 1 | 1 | yes |
| A2 | NAME-NEAR-ROLE | `08c8ccc18879` | `tests/fixtures/talent_feed.json` | 39 | 1 | 1 | yes |
| A3 | NAME-NEAR-ROLE | `8a9a5ff2e349` | `tests/fixtures/talent_pipeline.json` | 39 | 1 | 1 | yes |
| A4 | NAME-NEAR-ROLE | `72741a3d2243` | `tests/fixtures/outreach_missed_followups.json` | 2 | 1 | 1 | no |
| A5 | PHONE-IN | `8108090afa73` | `tests/fixtures/outreach_missed_followups.json` | 2 | 1 | 1 | no |
| A6 | PHONE-NANP | `2b3832ebcdee` | `tests/fixtures/outreach_missed_followups.json` | 2 | 1 | 2 | no |
| A7 | SIGNOFF-NAME | `1974ecc3151e` | `tests/fixtures/outreach_missed_followups.json` | 2 | 1 | 1 | no |
| A8 | SIGNOFF-NAME | `334275e3e104` | `tests/fixtures/outreach_missed_followups.json` | 2 | 1 | 1 | no |
| A9 | SIGNOFF-NAME | `b237797ddef9` | `tests/fixtures/outreach_missed_followups.json` | 2 | 1 | 1 | no |

Distinct individuals: A4/A6/A7 are one person; A1, A2, A3, A5, A8, A9 are six
more. **At least 7 third-party individuals.**

Files carrying class A:

| Path | A-hits | Live at HEAD |
|---|---|---|
| `tests/fixtures/outreach_missed_followups.json` | 6 | no (history-only blob) |
| `tests/fixtures/talent_feed.json` | 2 | yes |
| `tests/fixtures/talent_pipeline.json` | 1 | yes |

### Class B, the repo owner's own

| Label | Shape | Handle | Path | Commits | Live at HEAD |
|---|---|---|---|---|---|
| B1 | NAME-NEAR-ROLE | `b1c9547f1745` | `tests/test_talent_shape.py` | 52 | yes |
| B2 | NAME-NEAR-ROLE | `bd827207a77b` | `tests/fixtures/outreach_missed_followups.json` | 2 | no |
| B3 | PERSON-URL | `a43259f95a79` | `_audit/_slices/_slice-saved-and-preference.md` | 23 | yes |

B1 is the owner's full name used as test data for a name-parsing function, and
the surrounding assertions also carry the given name and surname separately.
B2 is the owner's given name in prose salutations inside the history-only
fixture. B3 is the owner's public code-forge profile URL.

**Plus commit metadata, which a blob census cannot see.** All 62 commits carry
one identity in both the author and committer fields: a display handle and a
platform-issued `users.noreply` address. Measured separately:

| Commit-metadata fact | Count |
|---|---|
| Distinct author identities | 1 |
| Distinct committer identities | 1 |
| Commits carrying it | 62 of 62 |
| Email-shaped strings in commit MESSAGES | 0 |
| `Co-authored-by` / `Signed-off-by` trailers | 0 |

The address is a platform noreply alias, not a mailbox, and the display handle
is the account name the repository would be published under anyway. This is
class B, unavoidable, and almost certainly acceptable -- but it is stated rather
than assumed.

### Class C, synthetic -- 72

| Shape | Distinct |
|---|---|
| EMAIL | 41 |
| PROFILE-SLUG | 19 |
| NAME-NEAR-ROLE | 8 |
| AT-HANDLE | 2 |
| PHONE-E164 | 1 |
| PHONE-IN | 1 |

**Every single email-shaped and slug-shaped value in the entire history is
synthetic.** 41 of 41 addresses sit at a reserved or stub domain; 19 of 19
profile slugs carry a synthetic token. There is no exception anywhere in 62
commits. The email and LinkedIn-URL half of the original seven-recruiter
scrub is RE-VERIFIED and holds -- which is precisely what makes the prose leak
in section 3 dangerous, because the verified-clean neighbours are what make the
file look safe.

### Class X, shape collisions -- 266

Matched a detector but is not an identity value. Recorded rather than discarded,
because a discarded false positive is indistinguishable from a missed check.

| Shape | Distinct | What they actually are |
|---|---|---|
| AT-HANDLE | 140 | numeric fragments inside URLs, Python decorator syntax, company handles and domains |
| NAME-NEAR-ROLE | 122 | job-advert boilerplate, section headings, company names, job titles |
| PERSON-URL | 2 | corporate social-media accounts, not personal profiles |
| PHONE-IN | 2 | ten-digit job-posting ids inside an `apply_url` value |

The two PHONE-IN collisions are the exact false-positive class the guard spec
predicts: a posting id in a URL is structurally identical to an Indian mobile.
Both were confirmed by reading the enclosing JSON key (`apply_url` /
`aggregator_application_link`), not assumed.

---

## 6. NEGATIVE SPACE -- what returned ZERO

A measured zero is a finding. Each of these ran over all 339 blobs and matched
nothing, and each was shown capable of matching by a planted control.

| Shape | Spec check | Result |
|---|---|---|
| LI-COMPANY-ID | check 4 | **0** across all history |
| LI-MEMBER-TOKEN | check 4 | **0** across all history |
| LI-URN-ID | check 4 | **0** across all history |
| CREDENTIAL-JWT | check 5 | **0** across all history |
| CREDENTIAL-COOKIE | check 5 | **0** across all history |

**Spec checks 4 and 5 are entirely clean in this repository, at HEAD and in
history.** No LinkedIn opaque identifier of any kind, and no credential or
session-token shape, has ever been committed. Check 4 is the check that found
what hand review missed in the sibling repositories; here it finds nothing, and
that zero is real rather than an artefact of a check that cannot fire.

Also zero:

- Class `A?` after adjudication: 0.
- Email addresses at a non-reserved domain: 0 of 41.
- Personal profile slugs without a synthetic token: 0 of 19.
- Identity shapes in commit messages: 0.
- Co-author or sign-off trailers: 0.
- Blobs skipped as binary: 0 (so no blob evaded scanning).
- New names found by the independent NAME-APPOSITIVE cross-check: 0.

### Boundary delta

The binding law requires token boundaries. The looser digit-boundary variant
from the guard spec was evaluated in parallel to prove the stricter law hides
nothing. It produced exactly **1** additional match, and that match is a
different span of the SAME `message_full` value already reported as A5. **The
stricter boundary concealed no finding.**

---

## 7. LIMITS -- what this census cannot certify

Stated plainly so nobody mistakes these numbers for a clean bill.

1. **A NAME STILL HAS NO SHAPE.** `NAME-NEAR-ROLE` fires only where a role word
   appears somewhere in the same blob. Measured: 206 blobs contain at least one
   capitalised multi-word run, and **36 of them contain no role word anywhere**,
   so any name in those 36 is unscreened by that check. Those 36 were reviewed
   by listing every capitalised run they contain; all proved to be company
   names, job titles or section headings, and the two deliberate leak specimens
   in `tests/fixtures/_specimens/` proved clean of human-readable identity. That
   is a review, not a proof.
2. **THE UNGATED NAME-CANDIDATE UNIVERSE IS 651 DISTINCT CAPITALISED RUNS.** 136
   of them were adjudicated. The rest were not individually read; they were
   filtered by the role-word gate and by the appositive cross-check. A name that
   appears in no role context, in no sign-off position, and beside no role
   appositive would survive all of it.
3. `SIGNOFF-NAME` requires a recognised closing word. A signature that opens
   with something outside that list is missed.
4. **Only these shapes were hunted.** Postal addresses, dates of birth, employee
   numbers, and free-text personal detail that is not a name, number, address or
   URL have no detector here at all.
5. The OPAQUE-TOKEN class is out of scope by design and is measured separately.
   Section 3 is the standing warning about reading the two censuses apart: this
   repository has now produced one file where the shaped fields were clean and
   the unshaped were not, and another where the structured fields were clean and
   the prose was not. **Neither census alone would have caught both.**

---

## 8. INPUTS FOR THE DECISION

This pass does not decide, and it has scrubbed nothing. What the decision-maker
needs in one place:

- **9 class-A values, at least 7 living third parties, in 3 files.**
- **6 of the 9 are invisible at HEAD.** They live in one blob reachable from 2
  commits. Any review that reads the working tree will see a clean file and
  conclude the repository is clean. It is not.
- **A HEAD-only fix cannot reach them.** The current HEAD already has the fixed
  version of that fixture. The exposure is entirely historical, so only history
  rewriting -- or not publishing -- removes it.
- **A history rewrite must be verified against the REMOTE, not the local tree.**
  This project already carries that scar from a sibling repository: local
  verification of a rewrite proves nothing, and only a mirror-clone scan of the
  remote does. This census was run against a mirror for exactly that reason and
  is re-runnable against one after any rewrite.
- **The published remote is the authority on what a fetcher receives.** These
  counts describe that mirror as of 2026-08-24, at `master` = `54876ae`.
- **Checks 4 and 5 are clean, and every email and profile slug is synthetic.**
  If the three fixtures in section 3 are dealt with, the human-readable identity
  surface of this repository goes to zero third-party values.

## 9. REPRODUCING THIS

```
python uplers/scripts/publish_identity_census.py --mirror <mirror> --json <out.json>
python uplers/scripts/publish_identity_census.py --control <dir-with-plants>
python uplers/scripts/publish_identity_census.py --mirror <mirror> --triage
```

`--triage` prints the residual values to stdout for a human. Send it to a
scratch location outside this repository, and delete it when done. The
adjudication used here is carried as a handle-keyed override map, which holds no
values and is therefore safe -- but it was kept OUT of the repository anyway,
because a stable map from handle to classification is one lookup table away from
being useful to someone who should not have it.
