"""No fixture on disk may carry a real contact route or a real pay figure.

WHAT HAPPENED, which is why this file exists. On 2026-08-23 seven fixtures were
captured from the live account by `scripts/capture_outreach.py` and committed at
fa22b49. Two of them carried data that must never sit in a repo:

  * `outreach_missed_followups.json` - the `missed-positive-reply-followups`
    route is the only one in that capture that returns OTHER PEOPLE. It shipped
    seven named third parties at named companies, their business email, their
    LinkedIn profile URL, the operator's own address in `from_email`, the Gmail
    thread ids, and the verbatim text of what those people wrote back.
  * `talent_preference.json` - his actual pay, in `current_ctc`,
    `expected_ctc`, `monthly_salary` and `ctc_breakdown`.

Both were scrubbed afterwards and the capture script was rewritten to redact
before it writes. That fixes the two files. It does not fix the CLASS, because
the next capture of the next route is written by a human who has to remember,
and the fixture directory is where the reminder is weakest: a fixture looks like
test data, so nobody reads it. This is the check that reads it, on every run.

TWO DETECTORS, BECAUSE THERE ARE TWO KINDS OF REDACTION, and using the wrong
one certifies nothing. The distinction is the whole design:

  * A MASKED field keeps its key and replaces its value. `employee_business_email`
    has to survive, because the shaper that surfaces these follow-ups reads it -
    delete the key and the fixture can no longer test the code it was captured
    for. So the only thing that can tell a scrubbed fixture from a leaking one is
    the VALUE, and the detector is a value walker over every string in the tree.
    A key-presence check here is not merely weak, it is BACKWARDS: it would
    condemn the correctly-scrubbed file, whose keys are all still there by
    design. See test_a_key_check_would_condemn_the_clean_contact_fixture.
  * A DELETED field has no value left to inspect. `current_ctc` is removed
    outright, so a value check over the scrubbed file walks straight past it and
    reports clean - and would report exactly as clean if the field came back
    tomorrow holding the real number, because the walker has no idea the key was
    ever supposed to be absent. For a deleted field the only signal is PRESENCE,
    so the detector is a key walker. See
    test_the_value_check_cannot_see_a_deleted_pay_field.

THE ALLOWLIST IS THE POSITIVE SPACE. "Real" is defined as "not one of the
placeholder shapes the scrub produces", rather than by trying to enumerate what
a real address looks like - a blocklist of known domains would pass the eighth
company. Placeholder emails use the RFC 2606 reserved `.invalid` TLD, which is
guaranteed never to resolve, so a placeholder that escapes into a live request
cannot reach a person.

FAILURES PRINT TRUNCATED VALUES ON PURPOSE. A guard that dumps the offending
string into the assertion message has copied the leak into the CI log, the
terminal scrollback, and whatever ships those onward - the same disclosure this
file exists to prevent, relocated to somewhere nobody thinks to scrub. The JSON
trail already says which field to fix, so the value only has to answer "is this
real or is it a placeholder the allowlist should have admitted", and three
characters plus a length answer that while routing nothing to anybody.

CONTROLS. Every assertion in the sweep says a leak is ABSENT, and that shape is
worthless unless the detector behind it demonstrably fires when a leak is
PRESENT. The controls marked `__CONTROL` below load a specimen and assert the
exact offender count.

THE SPECIMEN IS SYNTHETIC AND COMMITTED, AND IT DID NOT USED TO BE. It was
`git show fa22b49:<path>` - the real capture, which was a better specimen in
every way except one: another process was allowed to delete it, and one did.
The privacy rewrite removed that blob from every published ref; the loader
returned None; None meant `pytest.skip`; a skip is not a failure. Measured on a
fresh clone of the rewritten remote, this file reported `10 passed, 2 skipped`,
and the two skipped tests were the only ones proving the detector still
detects. It could have been commented out and nothing would have gone red.

Two rules came out of that, and both are load-bearing here:

* A control may not DEPEND on history it does not own. History is mutable by
  policy - rewrites, shallow clones, retention - and a control whose evidence
  lives there has an expiry date that nothing announces.
* ABSENCE OF THE SPECIMEN IS A FAILURE, NOT A SKIP. A skip cannot be
  distinguished from "not applicable on this machine", which is precisely the
  disguise the defect above wore for as long as it lasted.
"""

from __future__ import annotations

import collections
import json
import re

from pathlib import Path

import pytest

TESTS_DIR = Path(__file__).resolve().parent
FIXTURE_DIR = TESTS_DIR / "fixtures"
REPO_ROOT = TESTS_DIR.parent

#: The specimens these controls calibrate against. COMMITTED FILES, not blobs
#: pulled out of git history.
#:
#: They used to be `git show fa22b49:<path>` - the real capture, still dirty,
#: still reachable. That was the better specimen right up until it wasn't: the
#: privacy rewrite removed those blobs from every published ref, and
#: `git_blob()` answered None, and `specimen()` turned None into `pytest.skip`.
#: A skip is not a failure, so CI stayed green while the two controls that
#: prove this detector still detects ANYTHING stopped running. Measured on a
#: fresh clone of the rewritten remote: `10 passed, 2 skipped` - and the
#: detector could have been commented out entirely without a single red build.
#:
#: A control calibrated against evidence that another process is allowed to
#: destroy is a control with a scheduled expiry date, and nothing announces the
#: date. So the specimens are synthetic and committed, which no rewrite, no
#: shallow clone and no missing git binary can take away.
#:
#: The values inside them satisfy two OPPOSING constraints at once, which is
#: the only reason this works: they do NOT match the placeholder allowlist
#: below - so this detector fires on them, which is the point - while still
#: being admitted by tests/test_pii_hygiene.py, which sweeps every tracked
#: file. `.invalid` is a reserved TLD and the slugs carry a synthetic token.
#: A specimen that tripped the hygiene guard would just move the problem.
#:
#: They live in a SUBDIRECTORY because `fixture_files()` globs `*.json`
#: non-recursively; a specimen sitting beside the real fixtures would be swept
#: as a leak and turn the very guards it calibrates red.
SPECIMEN_DIR = FIXTURE_DIR / "_specimens"
CONTACT_BLOB = SPECIMEN_DIR / "outreach_contact_leak.json"
PAY_BLOB = SPECIMEN_DIR / "talent_pay_leak.json"

# Deliberately loose: it is a DETECTOR, not a validator. Anything that would
# read as an address to a human scanning the file has to trip it, because the
# question is "did a real route land on disk", not "is this RFC 5322 legal".
EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")

# Scheme is OPTIONAL and that is load-bearing. `www.linkedin.com/in/someone`
# with no scheme is exactly as much of a route to a named human as the https
# form, and a pattern anchored on "https://" would wave it through.
LINKEDIN_URL = re.compile(r"(?:https?://)?[\w.-]*linkedin\.com/in/[^\s\"',]*",
                          re.IGNORECASE)

# The allowlist. Both are FULL-STRING anchored against the matched substring,
# not against the field, so an address embedded in a sentence is judged on the
# address rather than on the sentence around it - which is not hypothetical:
# on the fa22b49 blob a real address sat inside the prose of `message_full`
# and inside `reply_summary`, in fields whose names give no hint of it.
PLACEHOLDER_EMAIL = re.compile(r"^[a-z]+\d+@example\.invalid$")
PLACEHOLDER_LINKEDIN = re.compile(r"^https://www\.linkedin\.com/in/redacted-contact-\d+$")

#: DELETED by the scrub, so PRESENCE at any depth is the signal. Keeping this a
#: key check rather than a value check is the point argued in the module
#: docstring, and both directions of that argument have a control below.
PAY_KEYS = frozenset(("current_ctc", "expected_ctc", "monthly_salary",
                      "ctc_breakdown"))

# The patterns above are the one thing a careless rewrite can silently destroy,
# and a hygiene detector that has quietly stopped detecting looks EXACTLY like a
# clean repo from a green suite. Same discipline as test_path_hygiene.py: assert
# the instrument at IMPORT time, so a broken pattern raises here instead of
# waiting for a test that would now always pass.
assert EMAIL.findall("a@b.co") == ["a@b.co"], "EMAIL stopped matching an address"
assert LINKEDIN_URL.findall("www.linkedin.com/in/x"), "LINKEDIN_URL lost its optional scheme"
assert PLACEHOLDER_EMAIL.match("contact1@example.invalid"), "allowlist lost the email shape"
assert not PLACEHOLDER_EMAIL.match("contact1@example.com"), "allowlist stopped requiring .invalid"
assert not PLACEHOLDER_EMAIL.match("contact@example.invalid"), "allowlist stopped requiring the digit"
assert PLACEHOLDER_LINKEDIN.match("https://www.linkedin.com/in/redacted-contact-1"), \
    "allowlist lost the linkedin shape"
assert not PLACEHOLDER_LINKEDIN.match("https://www.linkedin.com/in/a-real-person"), \
    "allowlist stopped pinning the redacted stem"


def walk_strings(node, trail="$"):
    """Every string in a parsed fixture, with the JSON path that reached it."""
    if isinstance(node, dict):
        for key, value in node.items():
            yield from walk_strings(value, "%s.%s" % (trail, key))
    elif isinstance(node, (list, tuple)):
        for index, item in enumerate(node):
            yield from walk_strings(item, "%s[%d]" % (trail, index))
    elif isinstance(node, str):
        yield (trail, node)


def walk_keys(node, trail="$"):
    """Every (key, JSON path) in a parsed fixture, at any depth."""
    if isinstance(node, dict):
        for key, value in node.items():
            here = "%s.%s" % (trail, key)
            yield (key, here)
            yield from walk_keys(value, here)
    elif isinstance(node, (list, tuple)):
        for index, item in enumerate(node):
            yield from walk_keys(item, "%s[%d]" % (trail, index))


def contact_leaks(node):
    """Every (kind, trail, value) that looks like a real contact route.

    Matches are tested against the allowlist INDIVIDUALLY via findall, so one
    real address hiding in a field that also contains placeholder text is still
    reported, and a placeholder quoted inside a sentence is still admitted.
    """
    for trail, text in walk_strings(node):
        for hit in EMAIL.findall(text):
            if not PLACEHOLDER_EMAIL.match(hit):
                yield ("email", trail, hit)
        for hit in LINKEDIN_URL.findall(text):
            if not PLACEHOLDER_LINKEDIN.match(hit):
                yield ("linkedin", trail, hit)


def pay_key_hits(node):
    """Every (kind, trail, value) where a deleted pay key came back."""
    for key, trail in walk_keys(node):
        if key in PAY_KEYS:
            yield ("pay-key", trail, "")


def redacted(value: str) -> str:
    """A leak rendered short enough to print and long enough to act on."""
    if not value:
        return "<key present>"
    return "%s... (%d chars)" % (value[:3], len(value))


def render(offenders) -> str:
    """The failure message: what, where, and how to think about it."""
    lines = ["%d offender(s) in tests/fixtures:" % len(offenders)]
    for name, kind, trail, value in offenders:
        lines.append("  %-34s %-9s %-46s %s"
                     % (name, kind, trail, redacted(value)))
    lines.append("")
    lines.append("values are truncated on purpose - printing a leak into a CI "
                 "log copies it somewhere new.")
    lines.append("re-scrub via scripts/capture_outreach.py (DROP deletes, MASK "
                 "replaces); do not hand-edit the value into something that "
                 "merely looks fake.")
    return "\n".join(lines)


def fixture_files():
    """Every .json under tests/fixtures, sorted so failures read the same twice."""
    return sorted(FIXTURE_DIR.glob("*.json"))


def load(path: Path):
    """Parse one fixture, naming the file if it will not parse."""
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except ValueError as exc:
        pytest.fail("%s is not parseable JSON: %s" % (path.name, exc))


def specimen(path: Path):
    """The synthetic leak specimen. ABSENT IS A FAILURE, never a skip.

    This used to reach into git history and `pytest.skip` when the object was
    out of reach - no git, a shallow clone, or history that no longer went back
    far enough. Every one of those reads as "not applicable here", and that is
    exactly the problem: a skip cannot be told apart from "the thing I exist to
    prove has been deleted". The privacy rewrite deleted it, and the skip
    reported the same green it had always reported.

    So absence is now RED. The specimen is a committed file; if it is missing,
    something removed a control's evidence, and that is a defect in the repo
    rather than a property of the machine running the suite.
    """
    if not path.exists():
        pytest.fail(
            "specimen %s is MISSING. It is a committed file and these controls "
            "cannot certify anything without it. Do not skip past this and do "
            "not weaken the assertions to match a smaller specimen: restore "
            "the file, or regenerate one that reproduces the counts asserted "
            "below." % path.relative_to(REPO_ROOT).as_posix())
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except ValueError as exc:
        pytest.fail("specimen %s is not parseable JSON: %s"
                    % (path.relative_to(REPO_ROOT).as_posix(), exc))


class TestNoFixtureCarriesAContactRoute:
    """The sweep. Every .json in tests/fixtures, every string, every depth."""

    def test_no_fixture_carries_a_real_contact_route(self):
        """An address or a LinkedIn profile outside the placeholder space."""
        offenders = []
        for path in fixture_files():
            for kind, trail, value in contact_leaks(load(path)):
                offenders.append((path.name, kind, trail, value))

        assert offenders == [], render(offenders)

    def test_no_fixture_carries_a_deleted_pay_key(self):
        """Pay is DELETED by the scrub, so the key coming back is the signal."""
        offenders = []
        for path in fixture_files():
            for kind, trail, value in pay_key_hits(load(path)):
                offenders.append((path.name, kind, trail, value))

        assert offenders == [], render(offenders)

    def test_the_sweep_actually_visited_the_fixtures__CONTROL(self):
        """__CONTROL for both sweeps above.

        `offenders == []` is trivially true over an empty file list, so a
        renamed directory, a changed glob or a fixture set that moved
        elsewhere would turn both guards green by walking nothing at all.
        This pins that the walk had real work to do, and names the one file
        that is known to carry masked contact fields - so the sweep cannot
        pass by quietly losing the only fixture it most needs to read.
        """
        names = [path.name for path in fixture_files()]

        assert names, "no fixtures walked - the sweep above certified nothing"
        assert "outreach_missed_followups.json" in names, names
        assert "talent_preference.json" in names, names

    def test_the_allowlist_is_load_bearing_not_vacuous__CONTROL(self):
        """__CONTROL. The clean fixture must EXERCISE the allowlist, not dodge it.

        If the scrub had deleted the contact keys instead of masking them, the
        sweep would still pass - on a file with nothing left to check. Then the
        allowlist would never run, and its correctness would stop mattering
        while the suite stayed green. So the scrubbed file has to contain
        placeholder-shaped values that the detector SEES and the allowlist
        ADMITS, in every row.
        """
        body = load(FIXTURE_DIR / "outreach_missed_followups.json")
        rows = body["data"]["rows"]

        admitted = [hit
                    for _, text in walk_strings(body)
                    for hit in EMAIL.findall(text)
                    if PLACEHOLDER_EMAIL.match(hit)]
        admitted_urls = [hit
                         for _, text in walk_strings(body)
                         for hit in LINKEDIN_URL.findall(text)
                         if PLACEHOLDER_LINKEDIN.match(hit)]

        assert len(rows) == 7, len(rows)
        # 7 rows x (contact_display, contact_value, employee_business_email,
        # to_email) = 28, plus one from_email per row = 35.
        assert len(admitted) == 35, len(admitted)
        assert len(admitted_urls) == 7, len(admitted_urls)


class TestTheDetectorFiresOnASpecimenLeak:
    """__CONTROL group. A guard shown only passing certifies nothing.

    A guard for this class of defect that has only ever been shown passing is
    indistinguishable from a guard with the detector commented out. These load
    a specimen that DOES leak and assert the exact offender count, so the
    difference is measured rather than assumed.

    The counts below were MEASURED against the original real capture and are
    reproduced exactly by the synthetic specimen - same seven rows, same six
    routing fields per row, same two addresses buried in prose. The specimen
    was built to those numbers rather than the numbers relaxed to fit it, so
    the calibration survived the substitution instead of being weakened by it.
    """

    def test_the_contact_detector_fires_on_the_committed_leak__CONTROL(self):
        """__CONTROL for test_no_fixture_carries_a_real_contact_route.

        MEASURED against fa22b49, not assumed: 44 hits over 7 rows. Forty-two
        sit in the six fields that ARE routes - six per row, five of them the
        third party's and one the operator's own `from_email` - plus two more
        buried in prose (`message_full`, `reply_summary`) where a field-name
        blocklist would never have looked. The breakdown is asserted per field
        rather than as a bare total so that a future disagreement about the
        number can be settled line by line instead of argued: a re-count that
        differs will say WHICH field moved.

        TWO LOWER FIGURES FOR THIS BLOB ARE ON THE RECORD AND NEITHER
        REPRODUCES: `_audit/2026-08-23-build-uplers.md` says it "matches the
        real contact strings 12 times", and 20 circulated separately. They do
        not agree with each other, and no counting rule over this object yields
        either - 44 raw hits, 42 excluding the two prose hits, 37 addresses and
        7 URLs, 17 distinct offending strings, 15 distinct values, 8 distinct
        addresses, 7 rows. 44 is confirmed by a SECOND, independent instrument
        rather than by this walker alone: over the same blob `grep -c "@"`
        returns 37 and `grep -c "linkedin.com/in"` returns 7. Both undercounts
        are recorded here rather than quietly corrected, because a leak audit
        that under-reports is the failure mode worth leaving a marker for.
        """
        hits = list(contact_leaks(specimen(CONTACT_BLOB)))
        by_field = collections.Counter(trail.rsplit(".", 1)[-1]
                                       for _, trail, _ in hits)

        assert len(hits) == 44, len(hits)
        assert dict(by_field) == {
            "contact_display": 7,
            "contact_value": 7,
            "employee_business_email": 7,
            "employee_linkedin_url": 7,
            "from_email": 7,
            "to_email": 7,
            "message_full": 1,
            "reply_summary": 1,
        }, dict(by_field)
        assert collections.Counter(kind for kind, _, _ in hits) == \
            collections.Counter({"email": 37, "linkedin": 7})

    def test_the_pay_detector_fires_on_the_committed_leak__CONTROL(self):
        """__CONTROL for test_no_fixture_carries_a_deleted_pay_key.

        The other half of the incident, and a different fixture, so the two
        detectors are calibrated independently. All four keys sat side by side
        under `$.talent`, which is also why the key walker has to recurse: a
        top-level scan of the document would have found none of them.
        """
        hits = sorted(trail for _, trail, _ in pay_key_hits(specimen(PAY_BLOB)))

        assert hits == [
            "$.talent.ctc_breakdown",
            "$.talent.current_ctc",
            "$.talent.expected_ctc",
            "$.talent.monthly_salary",
        ], hits

    def test_the_scrub_actually_cleaned_those_two_blobs__CONTROL(self):
        """__CONTROL for the pair above: same detector, same two files, after.

        Without this, the two controls prove only that the detector fires on
        SOMETHING old. Running it across the commit boundary is what shows the
        instrument distinguishes the leaking version from the fixed one, which
        is the only property the sweep actually relies on.
        """
        assert list(contact_leaks(load(FIXTURE_DIR / "outreach_missed_followups.json"))) == []
        assert list(pay_key_hits(load(FIXTURE_DIR / "talent_preference.json"))) == []


class TestTheAllowlistDoesNotSwallowEverything:
    """__CONTROL group. A guard that passes everything and a guard that fails
    everything are equally useless, and from a green suite they look identical.
    These pin both edges on synthetic input, so they run everywhere - including
    the shallow clone where the git-backed controls above skip.
    """

    def test_a_stranger_fires_and_a_placeholder_does_not__CONTROL(self):
        """__CONTROL. The two halves the allowlist has to keep apart."""
        leaking = {"employee_business_email": "attacker@evil.example.com"}
        clean = {"employee_business_email": "contact1@example.invalid"}

        assert list(contact_leaks(leaking)) == [
            ("email", "$.employee_business_email", "attacker@evil.example.com")
        ]
        assert list(contact_leaks(clean)) == []

    def test_the_allowlist_is_narrow_not_merely_present__CONTROL(self):
        """__CONTROL. Near misses, each wrong in one way, all still refused.

        The failure mode this rules out is an allowlist loose enough to admit
        anything vaguely placeholder-ish. `.com` instead of the reserved
        `.invalid` is a domain that RESOLVES; a missing digit is the shape a
        hand-edit produces; and a real LinkedIn profile under the right host is
        the exact string the incident shipped seven of.
        """
        near_misses = (
            "contact1@example.com",
            "contact@example.invalid",
            "contact1@example.invalid.co",
            "https://www.linkedin.com/in/a-real-person",
            "www.linkedin.com/in/a-real-person",
            "https://www.linkedin.com/in/redacted-contact-",
        )

        for value in near_misses:
            assert list(contact_leaks({"field": value})), \
                "allowlist wrongly admitted %r" % value

    def test_an_address_embedded_in_prose_is_still_caught__CONTROL(self):
        """__CONTROL for the findall design, and for a real property of fa22b49.

        Two of that blob's 44 hits were inside free text, not in a field whose
        name suggests contact data. Judging the whole field against the
        allowlist would still have caught these - but only by accident, since
        the surrounding sentence fails the anchored pattern anyway. The case
        that needs findall is a real address sitting NEXT TO a placeholder,
        where a whole-field check reports one hit and a per-match check
        reports the right one.
        """
        mixed = {"message_full": "reply to contact1@example.invalid or "
                                 "real.person@corp.example.org"}

        hits = list(contact_leaks(mixed))

        assert hits == [("email", "$.message_full", "real.person@corp.example.org")], hits


class TestTheTwoDetectorsAreNotInterchangeable:
    """__CONTROL group for the design argument in the module docstring.

    Both directions are measurable on real files, so neither is a matter of
    taste. Swap the instruments and one guard silently stops working while the
    other starts manufacturing failures.
    """

    def test_the_value_check_cannot_see_a_deleted_pay_field__CONTROL(self):
        """__CONTROL. Why pay is a KEY check.

        The scrubbed preference fixture has no pay keys, so there is no value
        for a value walker to inspect and it reports clean - and it would
        report just as clean if `current_ctc` returned tomorrow holding the
        real figure, because nothing in a value walker knows the key was meant
        to be gone. A number is also not a string, so it never reaches a string
        walker at all. Only presence carries the signal.
        """
        returned = {"talent": {"current_ctc": 2400000, "expected_ctc": "32 LPA"}}

        # The value walker: blind to the integer entirely, and the string
        # "32 LPA" trips neither pattern. Zero hits on a live leak.
        assert list(contact_leaks(returned)) == []
        # The key walker sees both.
        assert sorted(trail for _, trail, _ in pay_key_hits(returned)) == [
            "$.talent.current_ctc", "$.talent.expected_ctc",
        ]

    def test_a_key_check_would_condemn_the_clean_contact_fixture__CONTROL(self):
        """__CONTROL. Why contacts are a VALUE check - the mirror failure.

        `employee_business_email` and `employee_linkedin_url` are MASKED, so
        they are still present in the correctly scrubbed file: the shaper that
        surfaces these follow-ups reads them, and deleting the keys would make
        the fixture unable to test the code it was captured for. A
        key-presence rule on contact fields therefore fires on the CLEAN file.
        That is the worse failure of the two, because the usual repair for a
        manufactured failure is to delete the field that tripped it - which
        would destroy the fixture to satisfy the instrument.
        """
        clean = load(FIXTURE_DIR / "outreach_missed_followups.json")
        contact_keys = {"employee_business_email", "employee_linkedin_url",
                        "contact_value", "to_email", "from_email"}

        present = sorted({key for key, _ in walk_keys(clean)} & contact_keys)

        assert present == sorted(contact_keys), present
        # ... and the value detector, the right instrument, passes the same file.
        assert list(contact_leaks(clean)) == []
