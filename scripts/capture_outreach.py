"""Capture the READ-ONLY routes behind the agent read-through, as fixtures.

Run against a live signed-in session. Writes one file per route into
`tests/fixtures/`, so the suite tests the shape Uplers actually sends rather
than a shape somebody invented - the same rule `capture_profile_fixture.py`
exists to enforce.

WHY A GUARD RATHER THAN CARE. Every route here lives under
``talent/outreach/*``, which is the namespace of Uplers' PAID outreach-agent
product, and one of its siblings (``consent-email-job-scan``) is a write that
changes what Uplers reads out of his mailbox. A typo in this file is therefore
not a failed capture, it is an unrequested change to his account. So the
method is pinned to GET and the path to an allowlist, in code, and a miss
raises before the client is built.

Rate discipline: his live session, one request at a time, with the client's
own inter-request delay left at the default rather than zeroed.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from uplers_server import endpoints  # noqa: E402
from uplers_server.session import SessionStore  # noqa: E402
from uplers_server.talent import TalentClient  # noqa: E402

OUT_DIR = REPO / "tests" / "fixtures"

#: (fixture stem, path, params). GET only - see the module docstring.
CAPTURES = (
    ("outreach_step", "talent/outreach/outreach-step", None),
    ("outreach_dashboard", "talent/outreach/get-outreach-dashboard-data", None),
    ("outreach_pending_jobs", "talent/outreach/pending-jobs", None),
    ("outreach_missed_followups", "talent/outreach/missed-positive-reply-followups", None),
    ("outreach_tailor_activity", "talent/outreach/agent-tailor-activity", None),
    ("talent_preference", "talent/get-preference", None),
    ("saved_filter_page", endpoints.EP_OPPORTUNITIES,
     {"is_saved_filter": 1, "pagination": 20, "page": 1}),
)

ALLOWED = {path for _, path, _ in CAPTURES}

#: Same belt-and-braces rule as the profile capture: a key Uplers adds after
#: this was written must not land on disk unnoticed.
SUSPICIOUS = re.compile(
    r"ctc|salary|compensation|dob|birth|phone|mobile|whatsapp|aadhaar|passport|"
    r"bank|token|password|otp|secret|authorization",
    re.IGNORECASE,
)


def normal_key(name: str) -> str:
    """One comparable spelling for a field name.

    `resumePath`, `resume_path`, `ResumePath` and `resume-path` are one field
    wearing four coats, and on 2026-08-24 the difference between two of them
    was the whole defect: `DROP` held exact snake_case names, Uplers answered
    camelCase, and a presigned resume URL walked straight through the gap.
    Folding the case and dropping the separators means every entry below names
    the FIELD rather than one of its spellings.
    """
    return re.sub(r"[^a-z0-9]", "", name.lower())


#: DELETED outright at any depth, so a test can assert their ABSENCE and a
#: future recapture cannot quietly reintroduce one. Pay, identity documents,
#: and every URL that resolves to a personal file. Compared through
#: `normal_key`, so one entry covers every casing of the same field.
DROP = (
    "current_ctc", "expected_ctc", "monthly_salary", "ctc_breakdown",
    "dob", "contact_number", "contact_number_country_code", "address",
    "email", "profile_pic", "profile_pic_url", "resume", "resume_url",
    "original_resume", "original_resume_url", "ra_resume_url",
    "ra_profile_pic_url", "ra_repository_url", "linkedin_id",

    #: MEASURED 2026-08-24 on `talent/outreach/preview-config`, which answers
    #: `$.data.resumePath.url` - a 466-character presigned S3 URL. Naming it
    #: here is the cheap half of that fix and the half that generalises least:
    #: the rule that would have caught it with NO name at all is
    #: `is_credential_url`, below.
    "resume_path",

    "token", "guest_token", "access_token",
)

#: THE PROSE CLASS, and the reason it is DROP rather than MASK.
#:
#: MEASURED 2026-08-24 on `outreach_missed_followups.json` at blob fa22b49.
#: Every STRUCTURED contact field in that file was correctly substituted --
#: `employee_name`, `employee_business_email`, `employee_linkedin_url`,
#: `contact_display`, `contact_value`, `from_email`, `to_email`, all seven
#: rows, all synthetic. Four of the seven rows still named real people,
#: because the scrubber walked the FIELDS and never walked the PROSE:
#: `message_full` and `reply_summary` carried quoted reply bodies with intact
#: email signature blocks -- a given name, a job title, an employer and two
#: phone numbers. One row's signature carried a person's name, title, employer
#: and number while the `employee_business_email` one key away had already
#: been rewritten to a reserved domain.
#:
#: THE STRUCTURED SCRUB IS WHAT MADE IT DANGEROUS. It is precisely because the
#: shaped fields read as synthetic that the file looked safe to anyone who
#: opened it. A clean-looking neighbour is not evidence about the field beside
#: it.
#:
#: SO PROSE IS NOT PATTERN-SCRUBBED, IT IS DELETED. A regex over free text is
#: a much weaker guarantee than key-based redaction -- the same argument
#: `contact_leaks` already makes about credential URLs, and the same one
#: `capture_agent_surface.py` makes when it refuses to capture
#: `get-recommended-jobs` at all. Deleting the key needs no enumeration of
#: what a signature block can contain.
#:
#: It is also what this server already decided for its own output.
#: ``uplers_agent_readthrough`` withholds reply bodies on the stated ground
#: that "the counterparty's email address and the verbatim body of their
#: message do not need to be printed into a transcript". A FIXTURE HAS NO MORE
#: RIGHT TO THEM THAN A TOOL RESULT DOES, and a fixture is worse: a tool result
#: scrolls away and a fixture is committed forever.
#:
#: The list below was found by WALKING ALL 42 FIXTURES, not by guessing names:
#: every string value was scored for body shape (>=120 chars, or embedded
#: HTML, or an embedded line break, or two-plus sentences over twelve-plus
#: words), and every key that scored was then checked for a reader in
#: `uplers_server/` and in `tests/`.
#:
#:   * `message_full`, `reply_summary` -- the measured leak. Another person's
#:     words. Previously MASK; now deleted, which is strictly stronger.
#:   * `company_pitch` -- MEASURED as the home of all THREE identity findings
#:     that are live at HEAD (`talent_feed.json` x2, `talent_pipeline.json`
#:     x1): real people named as a team lead, a founder and a CEO/CTO, each
#:     with a biographical sentence. Located by recomputing the census's
#:     published sha256 handles, so no value had to be read to find them.
#:   * `tech_stack_details`, `frontend_message`, `prerequisites` --
#:     multi-paragraph narrative, some with line breaks, and ZERO readers in
#:     the server or the suite. Nothing is lost.
#:
#: DELIBERATELY NOT HERE, each with its reason, because a silent omission is
#: indistinguishable from an oversight:
#:   * `description`, `about`, `JobDescription`, `title` -- job-advert prose
#:     with LIVE readers (`shaping.html_to_text`, `talent_shape`,
#:     `agent_surface`) and live assertions. Deleting them would empty the
#:     surfaces the fixtures exist to pin. They are covered instead by the
#:     SIGNOFF-NAME and PHONE-NANP arms of `contact_leaks`, which CONDEMN the
#:     fixture rather than half-clean it.
#:   * `job_description` -- 3 narrative values in `talent_profile.json` with no
#:     reader, so it LOOKS free to delete, and it is not. MEASURED: `normal_key`
#:     folds `job_description` and `JobDescription` onto the same entry, so
#:     listing either one deletes BOTH, and `JobDescription` is 36 values read
#:     by `shaping.html_to_text`. The folding that closed the 2026-08-24
#:     camelCase defect is the same folding that makes these two one field, and
#:     it cannot be had one way only. Caught by simulating the redaction over
#:     all 42 fixtures and reading which keys vanished -- not by inspection.
#:   * `discard_reason` -- platform-canned text, and `test_outreach` asserts it
#:     non-empty on every row.
#:   * `objective` -- his own profile summary, not correspondence, and
#:     `test_talent_profile_real` asserts it truthy.
#:   * `gmail_template`, `linkedin_template`, `message_gmail`,
#:     `message_linkedin` -- his own words, already MASK-replaced in WHOLE (not
#:     pattern-scrubbed), and read by the shapers that report "a template
#:     exists". A whole-value replacement is exactly as leak-proof as a delete.
PROSE_DROP = (
    "message_full",
    "reply_summary",
    "company_pitch",
    "tech_stack_details",
    "frontend_message",
    "prerequisites",
)

DROP = DROP + PROSE_DROP

#: MASKED rather than dropped, and the difference is deliberate.
#:
#: `missed-positive-reply-followups` is the only route here that returns OTHER
#: PEOPLE - named humans at named companies, their business email, their
#: LinkedIn profile, and the words they wrote back. Deleting those keys would
#: make the fixture unable to test the shaper that exists to surface them, so
#: the KEY survives and the VALUE is replaced by a synthetic of the same shape.
#: Placeholders use the RFC 2606 reserved `.invalid` TLD, which can never
#: resolve, so a fixture that leaks into a request cannot reach anybody.
#:
#: `reply_category` is NOT masked: it is a platform-generated enum, not a
#: person's words, and it is the field the shaper actually reads.
#: `thread_subject` is likewise Uplers' own template output, not correspondence.
#:
#: `message_full` and `reply_summary` USED TO BE HERE and are now in
#: `PROSE_DROP`. A mask over prose was never wrong so much as unnecessary: the
#: key exists to let a shaper read a value, and no shaper reads those two.
#: `gmail_thread_id` also left, for `OPAQUE_ID` -- see below for why a
#: shape-preserving substitute beats `redacted-thread-%d` there.
MASK = {
    "contact_display": "contact%d@example.invalid",
    "contact_value": "contact%d@example.invalid",
    "employee_business_email": "contact%d@example.invalid",
    "to_email": "contact%d@example.invalid",
    "from_email": "operator%d@example.invalid",
    "employee_linkedin_url": "https://www.linkedin.com/in/redacted-contact-%d",
    "employee_name": "Redacted Contact %d",

    # Added for `capture_agent_surface.py`. These are HIS OWN words and HIS OWN
    # mailbox rather than a third party's, which is why they are masked and not
    # dropped: a shaper that reports "a Gmail template exists" or "the follow-up
    # message is set" needs the KEY to survive, and needs nothing of the value.
    #
    # `gmail_email` is the connected mailbox address, echoed by three routes.
    # The templates and follow-up messages are multi-paragraph self-descriptions
    # carrying his employer history, his LinkedIn URL and his notice period.
    "gmail_email": "operator%d@example.invalid",
    "gmail_template": "<p>Redacted outreach template %d.</p>",
    "linkedin_template": "<p>Redacted outreach template %d.</p>",
    "message_gmail": "<p>Redacted follow-up message %d.</p>",
    "message_linkedin": "<p>Redacted follow-up message %d.</p>",
}

#: THE OPAQUE-HANDLE CLASS -- REPLACED, and the difference from MASK matters.
#:
#: MEASURED across the published mirror: 142 distinct live handles, none of
#: which any shape check can see. They are the failure mode the other two
#: classes cannot reach -- a value with NO recognisable personal shape, under a
#: key that reads like an encoding artefact, sitting beside fields that were
#: correctly substituted. The sibling specimen
#: `tests/fixtures/_specimens/outreach_contact_leak.json` is the proof: every
#: field with a personal SHAPE was replaced and `outreach_employee_id` was
#: kept verbatim, so the "sanitised" specimen still names the same seven real
#: people by their platform id.
#:
#: WHY REPLACE AND NOT DROP. A fixture exists to pin a shape. Deleting
#: `enc_id` from 380 rows would break the round-trip these files are for, and
#: deleting `talent_id` would delete the join key that makes a row belong to a
#: row. So the KEY survives, the VALUE is destroyed, and the substitute keeps
#: the ORIGINAL'S SHAPE: same length, same alphabet, separators preserved in
#: place. `alnum(32)` stays `alnum(32)`; `alnum_dash(17)` keeps its dash where
#: it was; a seven-digit integer stays a seven-digit integer rather than
#: becoming a string.
#:
#: WHY DETERMINISTIC. The same original maps to the same replacement in every
#: file, so REFERENTIAL INTEGRITY SURVIVES: the 210 rows that shared one
#: `talent_id` across four fixtures still share one, and a test that joins
#: `talent_profile.json` to `talent_preference.json` still joins.
#:
#: THE MAPPING IS ONE-WAY. It is a SHA-256 keystream, so there is no inverse
#: and no table anywhere that reverses it -- which is the point: a reversible
#: substitution plus a key is the de-anonymisation artefact
#: `test_pii_hygiene.test_no_mapping_table_of_real_values` exists to forbid.
#: THE SALT IS NOT A SECRET, because destruction rather than reversibility is
#: the goal: the original is gone from the file, and publishing the salt does
#: not bring it back.
#:
#: ONE HONEST LIMIT, stated rather than glossed. "No inverse" is not "no
#: brute force". `alnum(32)` is far out of reach, but a SEVEN-DIGIT id has
#: only 10^7 candidates, so with a published salt anyone can enumerate the
#: space and recover it. For the digit-shaped handles the tracked salt buys
#: obfuscation, not destruction. That is why `SALT_FILE` exists: drop a line
#: of text at `scripts/.redaction_salt` (untracked, gitignored) before a
#: re-derivation and the digit classes become genuinely unrecoverable too. The
#: default is the tracked constant so a capture is reproducible out of the box.
REDACTION_SALT_DEFAULT = "uplers-fixture-redaction-salt-2026-08-24"
SALT_FILE = Path(__file__).resolve().parent / ".redaction_salt"


def _load_salt() -> str:
    try:
        text = SALT_FILE.read_text(encoding="utf-8").strip()
    except OSError:
        return REDACTION_SALT_DEFAULT
    return text or REDACTION_SALT_DEFAULT


REDACTION_SALT = _load_salt()

#: Keys whose VALUE is an account-scoped or third-party handle. Compared
#: through `normal_key`, so `TalentEncId` and `talent_enc_id` are one entry.
#:
#: The last four are the ones no published identifier list contains. An
#: audit-trail column is not metadata: `created_by` names a USER of the
#: platform, and on a staff-operated talent board that user is an employee. It
#: was proven to be a person-id space rather than a per-table counter by
#: cardinality -- one value appears under `created_by`, `published_by` AND
#: `ta_id`, and `ta_id` is the Talent Acquisition contact, who is a human.
OPAQUE_ID = (
    "enc_id", "enc_id_nda", "enc_id_org", "TalentEncId",
    "talent_id", "user_id", "talent_gmail_email_id", "gmail_thread_id",
    "outreach_employee_id",
    "created_by", "published_by", "closed_by", "ta_id",
)

#: MEASURED FLOOR, not a guess. `acceptance_by`, `self_applied_by` and some
#: rows of `created_by` / `closed_by` hold only `0` and `1` -- booleans wearing
#: an id's name. Substituting one would corrupt a flag while pretending to
#: protect a person. Every real handle in this repo is 6 characters or longer
#: (`digits(4-7)`, `alnum_dash(17)`, `alnum(32)`); every sentinel is 1. A floor
#: of 4 separates them with room to spare, and it also passes over the empty
#: string, which `enc_id` really does carry in some rows.
OPAQUE_MIN_LEN = 4

#: What the redaction actually consults. Derived once from the lists above
#: so a spelling-insensitive lookup and a human-readable list cannot drift.
DROP_NORMAL = frozenset(normal_key(name) for name in DROP)
MASK_NORMAL = {normal_key(name): template for name, template in MASK.items()}
OPAQUE_NORMAL = frozenset(normal_key(name) for name in OPAQUE_ID)


def _keystream(value: str):
    """Endless salted bytes, derived from `value` and nothing else.

    Derived from the VALUE rather than from a counter over the document, which
    is what makes the substitution stable across files and across runs.
    """
    block_no = 0
    while True:
        seed = "%s\x00%d\x00%s" % (REDACTION_SALT, block_no, value)
        for byte in hashlib.sha256(seed.encode("utf-8")).digest():
            yield byte
        block_no += 1


def synthetic_like(value):
    """A deterministic, one-way stand-in wearing `value`'s exact shape.

    Digits become digits, lowercase becomes lowercase, uppercase becomes
    uppercase, and everything else - dashes, underscores - is kept where it
    stood. An `int` comes back an `int` of the same digit count, with a
    non-zero lead so it cannot silently shorten.

    Anything below `OPAQUE_MIN_LEN`, and anything that is not a string or a
    plain int, is returned UNCHANGED. `bool` is excluded explicitly: in Python
    it is an `int`, and rewriting `True` to `False` would be a data corruption
    dressed as a redaction.
    """
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        return value
    text = str(value)
    if len(text.lstrip("-")) < OPAQUE_MIN_LEN:
        return value

    stream = _keystream(text)
    out = []
    for index, char in enumerate(text):
        if "0" <= char <= "9":
            # No leading zero for an int: `int("0123456")` is six digits, and a
            # fixture that quietly changes an id's WIDTH has changed its shape.
            digits = "123456789" if (index == 0 and isinstance(value, int)) else "0123456789"
            out.append(digits[next(stream) % len(digits)])
        elif "a" <= char <= "z":
            out.append(chr(ord("a") + next(stream) % 26))
        elif "A" <= char <= "Z":
            out.append(chr(ord("A") + next(stream) % 26))
        else:
            out.append(char)

    replaced = "".join(out)
    return int(replaced) if isinstance(value, int) else replaced


def redaction_of(name: str):
    """"DROP", "MASK", "REPLACE" or None - what the redaction does to a field.

    The one place that question is answered, so a capture script printing a
    key inventory reports what the redaction WILL do rather than what a
    second, hand-kept copy of the lists happens to believe.
    """
    folded = normal_key(name)
    if folded in DROP_NORMAL:
        return "DROP"
    if folded in MASK_NORMAL:
        return "MASK"
    if folded in OPAQUE_NORMAL:
        return "REPLACE"
    return None


#: THE LOAD-BEARING HALF OF THE 2026-08-24 FIX, and the reason it reads the
#: VALUE instead of adding one more name to `DROP`.
#:
#: A presigned object-storage URL is not a reference to a document, it IS the
#: document: the signature in its query string is a bearer credential, so
#: whoever holds the string downloads the file until it expires. A key list can
#: only ever catch the names somebody already enumerated, and `resumePath` got
#: through precisely because nobody had - it was camelCase, and it kept its URL
#: one level down under `.url`. A rule that reads the value needs no
#: enumeration: it catches the next unnamed key on the day the API adds it.
#:
#: Two shapes count, and either alone is enough:
#:   * a SIGNATURE PARAMETER, which is unambiguous - a signed URL exists to be
#:     handed to somebody who is not authenticated;
#:   * an OBJECT-STORAGE HOST, because an unsigned URL into a bucket is still a
#:     direct address for a stored file, and `DROP` has said "every URL that
#:     resolves to a personal file" since it was written.
#:
#: The known cost of the host half: a company logo served out of S3 would be
#: masked too. That is a fixture losing a decoration, and it is worth it. As of
#: 2026-08-24 no tracked file in this repo matches either shape, so the rule
#: costs nothing already committed - measured, not assumed.
SIGNED_URL_PARAM = re.compile(
    r"[?&](?:X-Amz-Signature|X-Amz-Credential|X-Goog-Signature|"
    r"AWSAccessKeyId|GoogleAccessId)=",
    re.IGNORECASE,
)
OBJECT_STORE_HOST = re.compile(
    r"(?:^|//|\.)(?:"
    r"s3(?:[.-][a-z0-9-]+)?\.amazonaws\.com"
    r"|storage\.googleapis\.com"
    r"|blob\.core\.windows\.net"
    r"|r2\.cloudflarestorage\.com"
    r"|[a-z0-9-]+\.digitaloceanspaces\.com"
    r")",
    re.IGNORECASE,
)

#: A value that is nothing but a URL. Free text that merely CONTAINS one is
#: deliberately not rewritten - see `contact_leaks` for why.
BARE_URL = re.compile(r"^\s*https?://\S+\s*$", re.IGNORECASE)

#: Resolves nowhere, by the same reserved-`.invalid` rule the contact
#: placeholders follow, and matches neither shape above so it cannot condemn
#: the fixture it was written into.
CREDENTIAL_URL_PLACEHOLDER = "https://redacted.invalid/object-%d"


def is_credential_url(text: str) -> bool:
    """True when `text` CONTAINS an address for a file in object storage."""
    return bool(SIGNED_URL_PARAM.search(text) or OBJECT_STORE_HOST.search(text))


def is_bare_credential_url(text: str) -> bool:
    """True when `text` IS such an address and nothing else."""
    return bool(BARE_URL.match(text)) and is_credential_url(text)


#: HANDLES INSIDE A URL, UNDER NO KEY AT ALL -- the third class, and the one
#: level deeper than the two above.
#:
#: `is_credential_url` reads a value; this reads INSIDE a value. Two live
#: examples, both measured at HEAD and both missed on a first pass by a scanner
#: that was looking for exactly this kind of thing:
#:
#:   * `ouid=` inside an ordinary Google Docs link, under keys called `JDURL`
#:     and `jd_path`. `ouid` is Google's obfuscated account id for whoever
#:     shared the document -- a third party. No key in this repo is named for
#:     it; a reviewer reads "a link to the JD" and moves on.
#:   * a 43-character signature parameter called `t` on 80 distinct
#:     `media.licdn.com` URLs, none of them expired.
#:
#: THE RULE IS NOT A PARAMETER LIST, DELIBERATELY. Both of those were missed
#: precisely BY a parameter list, and the fix that held was to parse every
#: query string and put every parameter through the same admission. A list can
#: only catch the names somebody already enumerated; this catches the next one
#: on the day the API adds it. It found a third value on its first run that no
#: census had inventoried: a 32-character `source=` token repeated across every
#: job-advert URL.
#:
#: The admission is value-shaped, and each clause exists to keep it narrow:
#:   * >= 16 characters -- an expiry (`e=1757505600`), a version (`v=beta`) and
#:     a ten-digit posting id (`gh_jid=`) all fall under it, and none of them
#:     is a handle;
#:   * alphabet limited to url-safe token characters;
#:   * NOT word-shaped, so `?sort=date_posted` and `?utm_campaign=spring_hiring`
#:     are left alone;
#:   * at least one digit, the digit-density floor that stops long English and
#:     long identifiers being admitted on length alone.
#: A parameter whose NAME normalises onto `OPAQUE_ID` is admitted regardless of
#: shape, so `?talent_id=1234567` is caught below the length floor.
URL_QUERY_PAIR = re.compile(r"(?<=[?&])([^=&#\s]+)=([^&#\s\"']*)")
URL_IN_TEXT = re.compile(r"https?://[^\s\"'<>\\)]+", re.IGNORECASE)
OPAQUE_TOKEN_CHARS = re.compile(r"^[A-Za-z0-9_-]+$")
WORD_SHAPED = re.compile(r"^[A-Za-z]+(?:[_-][A-Za-z]+)*$")
OPAQUE_PARAM_MIN_LEN = 16


def is_opaque_token(value: str) -> bool:
    """True when a query-parameter VALUE is an opaque handle by shape alone."""
    if len(value) < OPAQUE_PARAM_MIN_LEN:
        return False
    if not OPAQUE_TOKEN_CHARS.match(value):
        return False
    if WORD_SHAPED.match(value):
        return False
    return any("0" <= char <= "9" for char in value)


def opaque_query_params(url: str):
    """(name, value) for every admitted parameter in one URL."""
    for match in URL_QUERY_PAIR.finditer(url):
        name, value = match.group(1), match.group(2)
        if not value:
            continue
        if normal_key(name) in OPAQUE_NORMAL or is_opaque_token(value):
            yield name, value


def redact_url_query(url: str) -> str:
    """Rewrite every admitted parameter value in place, leaving the rest byte
    for byte as it was.

    The substitution is spliced into the ORIGINAL string rather than the query
    being parsed and re-serialised. Re-serialising re-encodes parameters nobody
    asked about -- a `+` becomes `%2B`, an unreserved character gains a percent
    escape -- and a fixture that exists to pin the shape Uplers really sends
    must not be quietly re-spelled by its own scrubber.
    """
    def rewrite(match):
        name, value = match.group(1), match.group(2)
        if not value:
            return match.group(0)
        if normal_key(name) in OPAQUE_NORMAL or is_opaque_token(value):
            return "%s=%s" % (name, synthetic_like(value))
        return match.group(0)

    return URL_QUERY_PAIR.sub(rewrite, url)


def prose_carries_opaque_param(text: str) -> bool:
    """True when free text CONTAINS a URL carrying an admitted parameter.

    The asymmetry with `redact_url_query` is the same one `contact_leaks`
    already draws for credential URLs, and it is what keeps the two from
    fighting: a BARE url is rewritten and is then clean, while a url buried in
    prose CONDEMNS the fixture instead of being half-cleaned. Without the
    split, the detector would flag the shape-preserving substitute the
    redaction had just written and delete every fixture it touched.
    """
    for match in URL_IN_TEXT.finditer(text):
        for _name, _value in opaque_query_params(match.group(0)):
            return True
    return False


#: SHAPE GAP 1 -- SIGN-OFF NAME. A given name has no LEXICAL shape: the
#: name check everywhere else in this project needs two or more titlecase
#: words, so a one-word sign-off matches nothing at all. A sign-off has a
#: POSITIONAL shape instead -- a closing word, then a line holding one or two
#: capitalised words and nothing else -- and that is the only handle a lone
#: first name offers. Three real third-party given names in this repository
#: were found by a human reading a file that every shape check had passed.
#:
#: BOTH LINE-BREAK FORMS ARE MATCHED, and that is not defensive coding: EVERY
#: REAL SIGN-OFF IN THIS REPOSITORY IS IN THE ESCAPED FORM. Inside a JSON
#: string a line break is the two characters `\r\n` on one physical line, so a
#: pattern anchored on a real newline sees none of them. `contact_leaks` walks
#: the PARSED document, where the same break is a real newline. One pattern
#: covers the parsed tree, the raw file, and a payload that arrived with
#: literal backslash-r-backslash-n in it.
SIGNOFF_LINE = re.compile(
    r"(?i)(?:^|[\r\n]|\\r\\n|\\n)\s*"
    r"(?:regards|warm regards|best regards|best|thanks|thank you|sincerely"
    r"|cheers|yours truly|kind regards|br)\s*[,.]?\s*"
    r"(?:[\r\n]|\\r\\n|\\n)\s*"
    r"([A-Z][a-zA-Z'\-]{1,19}(?: [A-Z][a-zA-Z'\-]{1,19})?)\s*"
    r"(?=[\r\n]|\\r\\n|\\n|$)"
)

#: SHAPE GAP 2 -- NANP PHONE. Both phone shapes this project inherited assume
#: an Indian mobile (ten digits opening 6-9) or a leading plus sign, so a US
#: number written NNN-NNN-NNNN was invisible to both. One real one was sitting
#: in a signature block. Token boundaries, never digit boundaries, so a longer
#: numeric id cannot be sliced into a phone.
PHONE_NANP = re.compile(
    r"(?<![A-Za-z0-9_])(?:\+?1[-.\s])?\(?[2-9]\d{2}\)?[-.\s]\d{3}[-.\s]\d{4}"
    r"(?![A-Za-z0-9_])"
)


#: Proof the redaction worked, re-read off disk rather than off the object that
#: was written. Anything matching these outside the placeholder space is a leak.
EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
LINKEDIN_PROFILE = re.compile(r"linkedin\.com/in/", re.IGNORECASE)
PLACEHOLDER_EMAIL = re.compile(r"^[a-z]+\d+@example\.invalid$")
PLACEHOLDER_LINKEDIN = re.compile(r"^https://www\.linkedin\.com/in/redacted-contact-\d+$")


def _is_replaceable(value) -> bool:
    """True when `synthetic_like` would actually rewrite this value.

    Asked BEFORE the recursion so a REPLACE key holding a container, a null, a
    sentinel or an empty string falls through and is walked normally instead of
    being handed to a substituter that would return it unchanged anyway.
    """
    return synthetic_like(value) is not value


#: Paths where an `enc_id`-family handle names a PUBLIC JOB POSTING or a GLOBAL
#: CATALOG ROW, not a person. Adjudicated 2026-08-24 against the path census in
#: `_audit/_slices/_slice-publish-opaque-tokens.md`.
#:
#: WHY AN EXEMPTION EXISTS AT ALL. `enc_id` is one key name covering two
#: different subjects. Under `talent_details` it is HIS PROFILE HANDLE - the
#: opaque census proved that one live, because this repo's own code sends it to
#: download his resume. Under `hrs.data[]` it is a requisition: a public job
#: posting, the same one the PUBLIC tier already indexes from Uplers' public
#: sitemap and serves through `uplers_get_opportunity` without any account at
#: all. Under `masters` it is a global skill or tool row, identical for every
#: user of the platform. Replacing those two buys no privacy and costs the
#: identifier-space test that documents a real distinction in Uplers' API.
#:
#: THE POLARITY IS THE LOAD-BEARING PART, and it is deliberately the awkward
#: way round: the default is REPLACE and this set is the only escape. A path
#: nobody enumerated therefore gets its handle replaced - over-broad, and safe.
#: An allowlist written the other way (replace only these paths) would leave a
#: person's handle real the first time Uplers adds a key, which is exactly how
#: `resumePath` and `outreach_employee_id` survived their scrubs.
#:
#: Trails are collapsed: every list index renders as `[]`, so one entry covers
#: a whole array.
PUBLIC_HANDLE_PATHS = frozenset({
    "$.enc_id",                                          # a requisition file's root
    "$.data[].enc_id",                                   # board rows
    "$.data.list[].hr_enc_id",                           # saved-jobs rows
    "$.hrs.data[].enc_id",                               # feed / pipeline rows
    "$.hrs.data[].hr.enc_id",
    "$.hrs.data[].ai_data.enc_id",
    "$.hrs.data[].ai_data.master_enc_id",
    "$.hrs.data[].strong_proficiencyskills[].enc_id",    # global skill catalog
    "$.hrs.data[].hr.strong_proficiencyskills[].enc_id",
    "$.masters.skills[].enc_id",
    "$.masters.tools[].enc_id",
})


def _collapse(trail: str) -> str:
    """`$.hrs.data[3].enc_id` -> `$.hrs.data[].enc_id`. Indices are not paths."""
    return re.sub(r"\[\d+\]", "[]", trail)


def names_a_person(trail: str, key: str) -> bool:
    """Does an opaque handle at this path identify a PERSON?

    True unless the collapsed path is in :data:`PUBLIC_HANDLE_PATHS`. The
    default is the strict answer on purpose - see the note on that set.
    """
    return _collapse("%s.%s" % (trail, key)) not in PUBLIC_HANDLE_PATHS


def redact(node, counter=None, trail="$"):
    """Five redaction layers at any depth. Returns a new tree.

      * a key naming a DROP field disappears -- pay, identity documents, every
        URL that resolves to a personal file, and PROSE;
      * a key naming a MASK field keeps its name and takes a synthetic value;
      * a key naming an OPAQUE_ID field keeps its name and takes a
        shape-preserving one-way substitute, so the fixture stays structurally
        valid and joinable while the handle stops addressing anybody;
      * a STRING VALUE that is a presigned object-storage URL is replaced
        whatever key holds it, because there the credential IS the value and
        the key was never the thing worth trusting;
      * a STRING VALUE that is a bare URL has every opaque QUERY PARAMETER
        rewritten, because a handle can ride inside a link under no key at all.

    The counter is shared by the placeholder-numbering layers so each
    placeholder is numbered and two masked fields never collapse into one
    indistinguishable value. It is keyed by NORMALISED name; `$credential-url`
    cannot collide with one, because a normalised name holds only `[a-z0-9]`.
    The OPAQUE layer takes no counter by design: its substitute is derived from
    the VALUE, which is what keeps the same original mapping to the same
    replacement in every file rather than to that file's ordinal.
    """
    if counter is None:
        counter = {}
    if isinstance(node, dict):
        out = {}
        for key, value in node.items():
            verdict = redaction_of(key)
            if verdict == "DROP":
                continue
            if verdict == "MASK" and isinstance(value, str) and value:
                folded = normal_key(key)
                counter[folded] = counter.get(folded, 0) + 1
                out[key] = MASK_NORMAL[folded] % counter[folded]
            elif (
                verdict == "REPLACE"
                and _is_replaceable(value)
                and names_a_person(trail, key)
            ):
                out[key] = synthetic_like(value)
            else:
                out[key] = redact(value, counter, "%s.%s" % (trail, key))
        return out
    if isinstance(node, list):
        return [
            redact(item, counter, "%s[%d]" % (trail, index))
            for index, item in enumerate(node)
        ]
    if isinstance(node, str):
        if is_bare_credential_url(node):
            counter["$credential-url"] = counter.get("$credential-url", 0) + 1
            return CREDENTIAL_URL_PLACEHOLDER % counter["$credential-url"]
        if BARE_URL.match(node):
            return redact_url_query(node)
    return node


def strings(node, trail="$"):
    if isinstance(node, dict):
        for key, value in node.items():
            yield from strings(value, "%s.%s" % (trail, key))
    elif isinstance(node, list):
        for index, item in enumerate(node):
            yield from strings(item, "%s[%d]" % (trail, index))
    elif isinstance(node, str):
        yield (trail, node)


def contact_leaks(node):
    """Every string that still looks like a real contact route or credential.

    `credential-url` is checked FIRST, and it fires on text that merely
    CONTAINS such a URL rather than only on text that is one. The asymmetry
    with `redact`, which rewrites only a bare URL, is deliberate: a presigned
    URL buried in an HTML description is a leak, but rewriting it would mean
    scrubbing inside free text - a much weaker guarantee than key-based
    redaction, and the exact reason `capture_agent_surface.py` refuses to
    capture `get-recommended-jobs` at all. So free text carrying a credential
    CONDEMNS the fixture instead of being half-cleaned.

    THE LAST THREE ARMS ARE THE PROSE BACKSTOP, and they exist because the
    prose class cannot be closed by `PROSE_DROP` alone. Four body-shaped keys
    have live readers and live assertions -- `description`, `about`,
    `JobDescription`, `title` -- so they stay in the fixture, and a signature
    block pasted into one of them would be exactly the 2026-08-24 leak again
    under a different key. They are not pattern-scrubbed; they CONDEMN. A
    capture that trips one is a fixture deleted and a human asked, which is the
    correct outcome for text nobody can safely rewrite.

    Both were measured against all 42 committed fixtures before being wired:
    SIGNOFF-NAME fires 0 times and PHONE-NANP fires 0 times, so neither arrives
    carrying a false-positive backlog. `prose_carries_opaque_param` likewise
    measured 0, because every handle-bearing URL in this repo sits under its
    own key as a bare URL, where the redaction rewrites it instead.
    """
    for trail, text in strings(node):
        if is_credential_url(text):
            yield ("credential-url", trail, text)
        elif EMAIL.search(text) and not PLACEHOLDER_EMAIL.match(text):
            yield ("email", trail, text)
        elif LINKEDIN_PROFILE.search(text) and not PLACEHOLDER_LINKEDIN.match(text):
            yield ("linkedin", trail, text)
        elif SIGNOFF_LINE.search(text):
            yield ("signoff-name", trail, text)
        elif PHONE_NANP.search(text):
            yield ("phone-nanp", trail, text)
        elif not BARE_URL.match(text) and prose_carries_opaque_param(text):
            yield ("opaque-url-param", trail, text)


def suspicious_keys(node, trail="$"):
    if isinstance(node, dict):
        for key, value in node.items():
            if SUSPICIOUS.search(key):
                yield "%s.%s" % (trail, key)
            yield from suspicious_keys(value, "%s.%s" % (trail, key))
    elif isinstance(node, list):
        for index, item in enumerate(node):
            yield from suspicious_keys(item, "%s[%d]" % (trail, index))


def leak_summary(leaks) -> str:
    """Name WHERE each leak is, never WHAT it says.

    Two reasons this is not `%r` of the tuples. The obvious one: a leak report
    that prints the leaked value copies personal data into the console
    scrollback and every log that captures it, which is the thing the redaction
    exists to prevent. The measured one: on 2026-08-23 a captured template
    contained an emoji, and printing it raised `UnicodeEncodeError` on a cp1252
    console **part-way through the capture run**, so the routes after it were
    never fetched. A diagnostic that can abort the job it is diagnosing is a
    defect. The trail is what a human needs to fix `DROP`/`MASK` anyway.
    """
    return ", ".join(
        "%s at %s" % (kind, trail) for kind, trail, _ in sorted(leaks)
    )


def write_fixture(target: Path, body) -> tuple:
    """Redact, write, re-read to prove it - and DELETE the file if it leaked.

    Returns `(bytes_on_disk, leaks)`, so a caller can report both AFTER the
    dangerous file is already gone. THE DELETE LIVES HERE, and that is the fix
    rather than a tidy-up.

    It used to live in each caller, on the line BELOW the one that printed the
    verdict, and on 2026-08-24 that ordering cost a live leak: the output was
    piped through `head`, the pipe closed, and the `BrokenPipeError` landed
    inside the report print of a route that had leaked - so the `unlink()`
    under it never ran, and a fixture holding a real LinkedIn profile URL
    survived on disk until it was removed by hand. Python block-buffers to a
    pipe, so the writes kept succeeding long after the reader was gone and the
    failure surfaced at a flush, well past the point the file had been written.
    It was the SECOND firing of one ordering bug: `leak_summary` records a
    `UnicodeEncodeError` from an emoji on a cp1252 console the day before.

    Reporting is the only step in a capture that can fail for reasons having
    nothing to do with the capture, so nothing that can fail may sit between
    the leak verdict and the unlink. That is also why the size is measured
    BEFORE the scan runs rather than between the scan and the delete: it leaves
    only an `if` in between.
    """
    clean = redact(body)
    target.write_text(json.dumps(clean, indent=2, sort_keys=True), encoding="utf-8")
    size = target.stat().st_size
    reread = json.loads(target.read_text(encoding="utf-8"))
    leaks = sorted(set(contact_leaks(reread))) + [
        ("suspicious-key", trail, "") for trail in sorted(set(suspicious_keys(reread)))
    ]
    if leaks:
        target.unlink()
    return size, leaks


async def main() -> int:
    token = SessionStore().token()
    if not token:
        print("no session - run uplers_login first")
        return 1

    for _, path, _ in CAPTURES:
        assert path in ALLOWED, path

    client = TalentClient(SessionStore().token)
    async with client:
        for stem, path, params in CAPTURES:
            target = OUT_DIR / ("%s.json" % stem)
            try:
                body = await client.get_json(path, params)
            except Exception as exc:                      # noqa: BLE001
                print("%-26s FAILED  %s: %s" % (stem, type(exc).__name__, exc))
                continue

            # `write_fixture` has ALREADY deleted the file if anything leaked.
            # Nothing below this line can strand a leaking fixture on disk,
            # however it fails.
            size, leaks = write_fixture(target, body)
            print("%-26s %6d bytes%s" % (
                stem, size,
                ("  LEAKED (fixture deleted): %s" % leak_summary(leaks))
                if leaks else "  clean",
            ))
            if leaks:
                print("  ^ fix DROP/MASK before re-running")
    print("requests made: %d" % client.requests_made)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
