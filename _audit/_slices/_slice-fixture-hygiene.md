# SLICE: fixture hygiene guard

FILE CREATED (the only file written): `tests/test_fixture_hygiene.py`, 495 lines,
12 tests, strict ASCII (verified: 0 bytes above codepoint 127), LF endings.
Nothing else in the repo was touched - `git status --short` shows exactly one
untracked path. No git state changed, no network call made.


## 1. THE DETECTOR - two instruments, because there are two kinds of redaction

The guard walks EVERY `*.json` in `tests/fixtures/` (20 files today) and applies
two independent detectors. The split is the load-bearing design decision, and
the brief was right to single it out.

### 1a. Contact routes - a VALUE check

`contact_leaks(node)` walks every string at every depth, yielding
`(kind, trail, value)` with a `$.data.rows[0].to_email`-style JSON trail.

    EMAIL                = [\w.+-]+@[\w-]+\.[\w.-]+
    LINKEDIN_URL         = (?:https?://)?[\w.-]*linkedin\.com/in/[^\s"',]*
    PLACEHOLDER_EMAIL    = ^[a-z]+\d+@example\.invalid$
    PLACEHOLDER_LINKEDIN = ^https://www\.linkedin\.com/in/redacted-contact-\d+$

Anything email-shaped or `linkedin.com/in`-shaped that is NOT admitted by the
two placeholder patterns is an offender. Three deliberate choices:

* **The allowlist is the positive space.** "Real" means "not a placeholder",
  never "matches a known-bad domain" - a blocklist passes the eighth company.
* **Scheme is OPTIONAL on the LinkedIn pattern.** `www.linkedin.com/in/someone`
  with no scheme is exactly as much of a route to a named human as the https
  form; a pattern anchored on `https://` waves it through.
* **The allowlist is tested against the MATCHED SUBSTRING (findall), not the
  whole field.** This is not decoration: on the `fa22b49` blob, two of the 44
  hits sat inside the free text of `message_full` and `reply_summary` - fields
  whose names give no hint they carry an address. A whole-field check happens
  to catch those (the surrounding sentence fails the anchored pattern anyway),
  but it fails the case that matters - a real address sitting NEXT TO a
  placeholder in one field.

### 1b. Pay - a KEY check, and this is the distinction the brief asked about

`pay_key_hits(node)` walks every KEY at every depth and fires on presence of
`current_ctc`, `expected_ctc`, `monthly_salary`, `ctc_breakdown`.

The instrument follows the redaction, not the field type:

* A **MASKED** field keeps its key and replaces its value.
  `employee_business_email` HAS to survive - the shaper that surfaces these
  follow-ups reads it, so deleting the key would make the fixture unable to
  test the code it was captured for. The only thing that separates a scrubbed
  file from a leaking one is therefore the VALUE. A key check here is not
  merely weak, it is BACKWARDS: it condemns the correctly-scrubbed file.
* A **DELETED** field has no value left to inspect. A value walker over the
  scrubbed preference file walks straight past `current_ctc` and reports
  clean - and would report exactly as clean if the field returned tomorrow
  holding the real number, because nothing in a value walker knows the key was
  meant to be absent. Worse, pay arrives as an integer, which never reaches a
  string walker at all. Only PRESENCE carries signal.

Both directions are proved by control, not asserted (section 2, controls 8-9).

### 1c. Failure reporting

All offenders are collected and reported together - file, JSON trail, and the
value TRUNCATED to 3 characters plus its length (`som... (34 chars)`); a
key-check hit renders as `<key present>`. A failure that prints the whole leak
has copied it into the CI log, the scrollback and whatever ships those onward,
which is the same disclosure the guard exists to prevent, relocated to
somewhere nobody thinks to scrub. The trail already says which field to fix, so
the value only has to answer "real, or a placeholder the allowlist should have
admitted" - 3 characters answer that and route nothing to anybody.


## 2. THE TESTS - 12, of which 10 are controls

Sweeps (2):
1. `test_no_fixture_carries_a_real_contact_route` - the contact sweep.
2. `test_no_fixture_carries_a_deleted_pay_key` - the pay sweep.

Controls (10), all marked `__CONTROL` in the docstring per repo convention:

3. `test_the_sweep_actually_visited_the_fixtures__CONTROL` - `offenders == []`
   is trivially true over an empty file list, so a renamed directory or a
   changed glob turns BOTH sweeps green by walking nothing. Proves the walk had
   work to do and names the two incident files. **Shown failing** against an
   empty directory: "no fixtures walked - the sweep above certified nothing".
4. `test_the_allowlist_is_load_bearing_not_vacuous__CONTROL` - if the scrub had
   DELETED the contact keys instead of masking them, the sweep would still pass,
   on a file with nothing left to check, and the allowlist would stop mattering
   while the suite stayed green. Pins 7 rows, 35 admitted placeholder emails,
   7 admitted placeholder URLs - i.e. the allowlist is exercised on real data.
5. `test_the_contact_detector_fires_on_the_committed_leak__CONTROL` - **the
   headline control.** Loads `fa22b49:tests/fixtures/outreach_missed_followups.json`
   via `subprocess` -> `git show` and asserts the exact offender count AND the
   per-field breakdown (section 3).
6. `test_the_pay_detector_fires_on_the_committed_leak__CONTROL` - same method
   on `fa22b49:tests/fixtures/talent_preference.json`; asserts the exact four
   trails. Calibrates the second detector independently of the first.
7. `test_the_scrub_actually_cleaned_those_two_blobs__CONTROL` - same detectors,
   same two files, working-tree version, expecting zero. Without this, 5 and 6
   prove only that the detector fires on SOMETHING old; running across the
   commit boundary is what shows it distinguishes leaking from fixed.
8. `test_a_stranger_fires_and_a_placeholder_does_not__CONTROL` - the brief's
   required pair: `attacker@evil.example.com` fires,
   `contact1@example.invalid` does not.
9. `test_the_allowlist_is_narrow_not_merely_present__CONTROL` - six near
   misses, each wrong in exactly one way, all still refused:
   `contact1@example.com` (a TLD that RESOLVES), `contact@example.invalid` (no
   digit - the shape a hand-edit produces), `contact1@example.invalid.co`,
   `https://www.linkedin.com/in/a-real-person`, the schemeless form of the
   same, and a truncated `redacted-contact-` stem with no number.
10. `test_an_address_embedded_in_prose_is_still_caught__CONTROL` - a field
    holding a placeholder AND a real address reports exactly one offender, the
    real one. This is what `findall` buys.
11. `test_the_value_check_cannot_see_a_deleted_pay_field__CONTROL` - why pay is
    a key check: a returned `{"current_ctc": 2400000, "expected_ctc": "32 LPA"}`
    yields ZERO hits from the value walker and both from the key walker.
12. `test_a_key_check_would_condemn_the_clean_contact_fixture__CONTROL` - the
    mirror, and the worse failure: all five contact keys ARE still present in
    the correctly-scrubbed file, so a key rule on contact fields fires on the
    CLEAN file. The usual repair for a manufactured failure is to delete the
    field that tripped it, which would destroy the fixture to satisfy the
    instrument.

Plus **7 import-time assertions** on the patterns themselves, following the
`test_path_hygiene.py` precedent: a hygiene detector that has quietly stopped
detecting is indistinguishable from a clean repo when viewed from a green
suite, so a broken pattern raises at import rather than waiting for a test that
would now always pass.

### Skip behaviour (verified, not assumed)

`git_blob()` returns `None` - and the control calls `pytest.skip` - for every
reason the specimen can be out of reach on a machine that is not this one: no
git on PATH (`OSError`), not a checkout, or a shallow clone lacking the object
(non-zero returncode), or an unparseable blob. Measured: bogus rev -> `None`,
bogus path -> `None`, real specimen -> `dict`. On this box the controls DO run:
`pytest -v -rs` reports 12 passed, **0 skipped**, so the git-backed assertions
genuinely executed rather than silently opting out.


## 3. OFFENDER COUNT ON THE `fa22b49` BLOB - MEASURED 44, NOT 20, NOT 12

**The brief's stated premise was wrong and this is the escalation.** The brief
said "measured for you: the real-address hit count on that blob is 20". A third
figure is on the record: `_audit/2026-08-23-build-uplers.md` says the blob
"matches the real contact strings 12 times". The two do not agree with each
other, and neither reproduces.

Measured on `git show fa22b49:tests/fixtures/outreach_missed_followups.json`:

    TOTAL contact hits ....................... 44   <- asserted
      of which email ......................... 37
      of which linkedin ...................... 7
    per field: contact_display 7, contact_value 7, employee_business_email 7,
               employee_linkedin_url 7, from_email 7, to_email 7,
               message_full 1, reply_summary 1

**Confirmed by a second, independent instrument.** Over the same blob,
`grep -c "@"` returns **37** and `grep -c "linkedin.com/in"` returns **7** -
37 + 7 = 44, matching the walker exactly. This is not one detector's opinion.

Every other counting rule I could construct, none of which gives 20 or 12:

    44  all (trail, value) hits                       <- what the test asserts
    42  excluding the two prose hits
    37  email hits only
    17  distinct offending strings
    15  distinct values (8 addresses + 7 URLs)
     8  distinct addresses (7 third parties + his gmail)
     7  rows / distinct LinkedIn URLs / distinct third-party domains

I could not reconstruct the provenance of either 12 or 20 and have not invented
one. Note the brief's own enumeration is also short: it names 5 third-party
domains (softtech-engr, ranium x2, sparkeighteen, blackline) where the blob
carries **7 distinct third-party domains** plus the operator's gmail.

**How this was resolved rather than fudged.** The assertion pins the exact
per-field breakdown, not a bare magic number, so a future re-count that differs
says WHICH field moved instead of starting an argument. Both undercounts are
recorded in the test docstring rather than quietly corrected, because a leak
audit that UNDER-reports is precisely the failure worth leaving a marker for.
If the lead wants 20 defended, it needs a stated counting rule - I could not
find one.


## 4. VERDICT: did the scrub map miss one file, or did it not exist yet?

**NEITHER. Both stories on the record are wrong, and the true one is a third
thing.** The lead's hypothesis - "the redaction map did not exist when the
capture ran and was added afterwards" - is contradicted by git.

### Evidence

1. `git log --follow -- scripts/capture_outreach.py` returns exactly TWO
   commits: `fa22b49` and `b547ad0` ("fix(fixtures): the capture redacts BEFORE
   it writes, and proves it after").
2. `git show fa22b49 --name-status` shows the script was **added in the same
   commit as all seven fixtures** (`A scripts/capture_outreach.py` alongside
   `A` for each fixture). So a redaction map DID exist at capture time: the
   `fa22b49` script carries a `DROP` tuple and a `scrub()` that deletes those
   keys at any depth. **It ran, on all seven files.**
3. `git show b547ad0 --name-status` touches exactly three paths: the script and
   the two contaminated fixtures. Nothing else needed fixing.

### Why it failed, and it failed differently on each of the two files

**On the contact file - the map was DELETE-ONLY and keyed on EXACT key names
that Uplers does not use.** The `fa22b49` DROP list was:

    email, contact_number, contact_number_country_code, address, profile_pic,
    profile_pic_url, resume, resume_url, dob, linkedin_id, token,
    guest_token, access_token

The keys actually carrying the third-party data are `contact_display`,
`contact_value`, `employee_business_email`, `to_email`, `from_email`,
`employee_linkedin_url`, `message_full`, `reply_summary`, `gmail_thread_id`.
**Not one of them is in that list.** `email` is in DROP, but no key in that
payload is literally named `email` - they are `to_email`, `from_email`,
`employee_business_email` - and `if key in DROP` is exact membership, not a
substring test. So every one of them sailed through a filter that was running.
The concept of MASKING (which is what that file needs, since the shaper reads
those keys) did not exist in the script at all until `b547ad0` added `MASK`.

**On the pay file - the keys were absent from DROP, and the one instrument that
DID see them was ADVISORY.** `current_ctc`, `expected_ctc`, `monthly_salary`
and `ctc_breakdown` were not in the `fa22b49` DROP list; `b547ad0` added them.
But the `fa22b49` script already had a `SUSPICIOUS` regex containing
`ctc|salary`, which matches all four. Look at what the `fa22b49` main loop does
with the result:

    clean = scrub(body)
    flagged = sorted(set(suspicious_keys(clean)))
    target.write_text(json.dumps(clean, ...), encoding="utf-8")   # UNCONDITIONAL
    print(... ("  SUSPICIOUS=%s" % flagged) if flagged else "")

**The file is written before the warning is printed, and nothing consults
`flagged`.** No `unlink`, no `continue`, no raise. The detector almost certainly
fired and printed `SUSPICIOUS=[...]` to the console, and the capture wrote and
committed the file anyway. `b547ad0` is exactly the fix for this: the write path
became `write_fixture()`, which re-reads off disk to prove the redaction and
whose caller does `target.unlink()` on a hit.

### The half of the lead's hypothesis that IS confirmed

"The other six were clean because they contained no contact data at all, not
because a filter caught anything" - **CORRECT, and measured.** Running the
detector over all seven `fa22b49` blobs: `outreach_step`, `outreach_dashboard`,
`outreach_pending_jobs`, `outreach_tailor_activity` and `saved_filter_page` all
return 0 contact hits and 0 pay keys. Those routes returned no contact or pay
data in the first place. The scrub caught nothing in them because there was
nothing there.

### Consequence for the record

`d35646a`'s claim - "an independent secret sweep over all eight files found
nothing sensitive - build-uplers had built its own scrub map in BEFORE
capturing" - is a TRUE clause wrapped around a FALSE one. A scrub map did exist
before capture. It simply did not cover the data that mattered, and the sweep
that pronounced the files clean was wrong. `2026-08-23-build-uplers.md` already
corrects the sweep half; the "built redaction in BEFORE capturing" half is
technically accurate and should not be flipped to "there was no map" - the
accurate statement is **"a map existed, ran, and was the wrong shape: exact-key
deletion where the payload needed value masking, with its only broad detector
wired to warn rather than to refuse."**

That is the transferable lesson, and it is why the guard shipped here is a
POST-CONDITION on the fixture directory rather than another pre-condition in
the capture script: a capture-time filter only ever catches what its author
thought to name, and this one proves the point twice over.


## 5. SUITE COUNTS

    tests/test_fixture_hygiene.py alone .......... 12 passed  (0 skipped)
    FULL SUITE before (baseline given, d5adc8b) .. 1214 passed
    FULL SUITE after ............................. 1226 passed in 41.32s

1226 - 1214 = 12, exactly the new tests. Zero breakage, zero skips, zero
warnings. The baseline in the brief re-measured as accurate (unlike the
offender count).


## 6. NOT DONE / FOR THE LEAD

* **The `fa22b49` blob is still in history and still pushed.** This slice adds
  the guard that catches the class going forward; it does NOT remediate the
  existing commit, which needs history surgery on a shared branch and is the
  operator's call. Unchanged from the earlier escalations in
  `_slice-saved-and-preference.md` S6b and `_slice-outreach-readthrough.md` 5(a).
* **`gmail_thread_id` is masked by the capture but NOT checked by this guard.**
  The brief scoped the detector to email-shaped and linkedin-shaped strings
  plus the pay keys, and thread ids are neither - they are opaque hex, with no
  shape that separates a real one from a placeholder without an allowlist on
  that specific field. Flagging rather than silently widening scope: if you
  want it covered, the clean instrument is a per-field rule requiring
  `^redacted-thread-\d+$` on that key, and I did not add it unasked.
* The `20` in the brief and the `12` in `2026-08-23-build-uplers.md` should be
  reconciled to 44 by whoever owns those documents; I only own the test file
  and did not edit either.
