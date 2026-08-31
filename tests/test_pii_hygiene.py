"""Personal-data hygiene guard over every tracked file in this repository.

WHY THIS FILE HUNTS BY SHAPE AND ALLOWLISTS THE SYNTHETIC
---------------------------------------------------------
The check this replaces was a committed list of real literal strings. A list
of real values IS a de-anonymisation key: it leaks exactly what it claims to
protect, and every reader of the repo gets a copy. So this module inverts the
polarity. It carries NO real value anywhere. It matches PII by SHAPE and then
lets a match through only when the value is provably fake -- a reserved
domain that can never resolve, an all-zero number, a slug carrying a
synthetic token. Fake values are safe to commit; real ones are not, so only
fake ones appear below.

Two consequences worth stating out loud:

  * When a check fires on something that is genuinely already synthetic, the
    repair is to WIDEN AN ALLOWLIST, never to narrow a shape and never to
    delete a check. Every widening below names the class it exists for.
  * When a check fires on something real, the repair is to fix the DATA. Do
    not add the value here. Adding it would rebuild the key.

Assertion messages never print a full identifier. CI logs are readable by
anyone who can read the build, so a guard that prints what it found has
merely moved the leak.

FILE LIST
---------
`git ls-files` from the repository root, so a file is covered the day it is
added rather than the day someone remembers to extend a hardcoded list.
Binary suffixes are skipped, as is this module itself -- it is full of
regexes that look exactly like the shapes it hunts.
"""

from __future__ import annotations

import ast
import functools
import re
import subprocess
from pathlib import Path

# --------------------------------------------------------------------------
# Repository walk
# --------------------------------------------------------------------------

BINARY_SUFFIXES = frozenset(
    {
        ".png", ".jpg", ".jpeg", ".gif", ".pdf", ".zip", ".db", ".ico",
        ".woff", ".woff2", ".ttf", ".pyc", ".so", ".dll", ".exe", ".whl",
    }
)

#: Dependency pins and lock files are dense with base16/base64 hashes that
#: collide with several shapes below. They hold no personal data by
#: construction: a hash is not a person.
LOCK_FILENAMES = frozenset(
    {"package-lock.json", "poetry.lock", "uv.lock", "cargo.lock", "yarn.lock"}
)

#: A 40-hex git SHA, which contains long digit runs that look like phones.
GIT_SHA40 = re.compile(r"(?<![0-9a-fA-F])[0-9a-f]{40}(?![0-9a-fA-F])")


def _repo_root() -> Path:
    """The directory holding .git, found by walking up from this file."""
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / ".git").exists():
            return parent
    raise RuntimeError(
        "test_pii_hygiene: no .git found above %s -- the guard cannot "
        "enumerate tracked files and must not silently pass." % here
    )


@functools.lru_cache(maxsize=1)
def _tracked_text_files():
    """(relpath, Path, text) for every tracked, non-binary, readable file.

    Raises rather than degrading. A hygiene guard that quietly scans nothing
    is worse than no guard at all: it manufactures a green tick.
    """
    root = _repo_root()
    self_rel = Path(__file__).resolve().relative_to(root).as_posix()
    proc = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=str(root),
        capture_output=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            "test_pii_hygiene: `git ls-files` failed in %s (exit %d): %s"
            % (root, proc.returncode, proc.stderr.decode("utf-8", "replace"))
        )
    out = []
    for raw in proc.stdout.split(b"\0"):
        rel = raw.decode("utf-8", "surrogateescape").strip()
        if not rel or rel == self_rel:
            continue
        path = root / rel
        if path.suffix.lower() in BINARY_SUFFIXES:
            continue
        if not path.is_file():
            continue
        data = path.read_bytes()
        if b"\x00" in data:
            continue
        out.append((rel, path, data.decode("utf-8", "replace")))
    return tuple(out)


def _is_pins_or_lock(rel: str) -> bool:
    name = Path(rel).name.lower()
    if name.startswith("requirements") and name.endswith(".txt"):
        return True
    if name.endswith(".lock"):
        return True
    return name in LOCK_FILENAMES


def _iter_lines(skip=None):
    """Yield (relpath, lineno, line) over the tracked text corpus."""
    for rel, _path, text in _tracked_text_files():
        if skip is not None and skip(rel):
            continue
        for lineno, line in enumerate(text.splitlines(), start=1):
            yield rel, lineno, line


# --------------------------------------------------------------------------
# Redaction -- assertion messages must never carry a full identifier
# --------------------------------------------------------------------------


def _fingerprint(value: str) -> str:
    kinds = []
    if any(c.isdigit() for c in value):
        kinds.append("digits")
    if any(c.isalpha() for c in value):
        kinds.append("letters")
    if any((not c.isalnum()) and (not c.isspace()) for c in value):
        kinds.append("punct")
    return "<%d chars, %s>" % (len(value), "+".join(kinds) or "empty")


def _redact(value: str) -> str:
    """First two characters, an ellipsis, the last two. Nothing else."""
    text = str(value)
    if len(text) >= 6:
        return "%s...%s" % (text[:2], text[-2:])
    return _fingerprint(text)


def _report(hits) -> str:
    return "\n".join("  " + h for h in hits)


# --------------------------------------------------------------------------
# Check 1 -- email shape
# --------------------------------------------------------------------------

EMAIL_SHAPE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,24}")

#: RFC 2606 / RFC 6761 reserve these. Nothing here can ever resolve or reach
#: a person, so an address in this space is safe to commit by construction.
RESERVED_EXACT_DOMAINS = frozenset(
    {"example.com", "example.org", "example.net", "localhost"}
)
RESERVED_DOMAIN_SUFFIXES = (
    ".invalid",          # reserved TLD
    ".example.com",      # WIDENED: subdomains of the reserved names are
    ".example.org",      # reserved too, and the suites use them for
    ".example.net",      # adversary/victim roles (attacker@evil.example.com)
)

#: Full domains used as unit-test stubs, kept explicit so the set stays
#: auditable. Every entry is a value that cannot belong to anybody.
#:   x.com, b.co        -- shortest-possible-address regex probes
#:   example.invalid.co -- WIDENED: a deliberate near-miss fixture proving
#:                         that ".invalid.co" is not the ".invalid" TLD.
STUB_EMAIL_DOMAINS = frozenset({"x.com", "b.co", "example.invalid.co"})


def _email_domain(addr: str) -> str:
    return addr.rsplit("@", 1)[-1].rstrip(".").lower()


def _email_allowed(addr: str) -> bool:
    domain = _email_domain(addr)
    if domain in RESERVED_EXACT_DOMAINS or domain in STUB_EMAIL_DOMAINS:
        return True
    return domain.endswith(RESERVED_DOMAIN_SUFFIXES)


def test_no_real_email_addresses():
    """No address outside the reserved/synthetic domain space."""
    hits = []
    for rel, lineno, line in _iter_lines(skip=_is_pins_or_lock):
        for match in EMAIL_SHAPE.finditer(line):
            addr = match.group(0)
            if _email_allowed(addr):
                continue
            hits.append(
                "%s:%d  EMAIL  %s  (domain %s not reserved/allowlisted)"
                % (rel, lineno, _redact(addr), _redact(_email_domain(addr)))
            )
    assert not hits, (
        "Email-shaped values at non-synthetic domains are tracked in this "
        "repo. Replace the DATA with a .invalid / example.* address; only "
        "widen STUB_EMAIL_DOMAINS for a domain that provably belongs to "
        "nobody.\n%s" % _report(hits)
    )


# --------------------------------------------------------------------------
# Check 2 -- phone shape
# --------------------------------------------------------------------------

PHONE_IN_SHAPE = re.compile(r"(?<![\d.])(?:\+?91[-\s]?)?[6-9]\d{9}(?![\d.])")
PHONE_E164_SHAPE = re.compile(r"\+\d{1,3}[-\s]?\d{6,12}")

#: Numbers reserved by convention for documentation and tests.
CLASSIC_TEST_NUMBERS = frozenset({"9876543210", "1000000000", "0000000000"})

#: WIDENED -- numeric-id contexts that collide with the ten-digit Indian
#: mobile shape. Job-board posting ids and opportunity ids run to ten digits
#: and start with 6-9 just as an Indian mobile does, so they fire on shape
#: alone. Each alternative below exists because an already-committed,
#: NON-PERSONAL identifier fired in that position:
#:   1. a posting id in a URL query string   ...?gh_jid=<10 digits>
#:   2. a REST resource path segment         /api/v1/.../<resource>/<id>
#:   3. the value of a key whose NAME ends in an id-ish token
#:                                           "id": <id>, "..._id": "<id>"
#: These allow a CONTEXT, never a value, so no identifier is recorded here
#: -- which is the whole point of this module. The known cost: a phone
#: hidden under a key named "*_id" would pass. A phone under any honest key
#: name (phone, mobile, contact, number) still fires.
PHONE_ID_CONTEXT = re.compile(
    r"(?:"
    r"[?&][A-Za-z0-9_]{0,24}(?:jid|job_id|jobid|posting_id|req_id)="
    r"|/[A-Za-z0-9_\-]+/(?:[A-Za-z0-9_\-]+/)*"
    r"|[\"']?[A-Za-z0-9_]*(?:id|uri|opp)[\"']?\s*[:=]\s*[\"']?"
    r")$",
    re.IGNORECASE,
)


def _phone_allowed(match_text: str) -> bool:
    digits = re.sub(r"\D", "", match_text)
    if not digits:
        return True
    candidates = {digits}
    for cc_len in (1, 2, 3):
        if len(digits) > cc_len:
            candidates.add(digits[cc_len:])
    for candidate in candidates:
        if candidate and set(candidate) == {"0"}:
            return True
        if candidate in CLASSIC_TEST_NUMBERS:
            return True
    return False


def _phone_line_skipped(rel: str, line: str) -> bool:
    return rel.lower().endswith(".md") and bool(GIT_SHA40.search(line))


def test_no_real_phone_numbers():
    """No phone-shaped run outside the zeroed/classic/known-id space."""
    hits = []
    for rel, lineno, line in _iter_lines(skip=_is_pins_or_lock):
        if _phone_line_skipped(rel, line):
            continue
        for name, pattern in (
            ("PHONE-IN", PHONE_IN_SHAPE),
            ("PHONE-E164", PHONE_E164_SHAPE),
        ):
            for match in pattern.finditer(line):
                value = match.group(0)
                if _phone_allowed(value):
                    continue
                if PHONE_ID_CONTEXT.search(line[: match.start()]):
                    continue
                hits.append("%s:%d  %s  %s" % (rel, lineno, name, _redact(value)))
    assert not hits, (
        "Phone-shaped values are tracked in this repo. Replace the DATA "
        "with an all-zero or classic test number; widen "
        "CLASSIC_TEST_NUMBERS / PHONE_ID_CONTEXT only for a value that is "
        "provably not a person's number.\n%s" % _report(hits)
    )


# --------------------------------------------------------------------------
# Check 3 -- LinkedIn personal slug
# --------------------------------------------------------------------------

LINKEDIN_SLUG = re.compile(r"(?:linkedin\.com)?/in/([A-Za-z0-9\-_%]{3,})")

#: A slug carrying one of these reads as obviously invented to any human,
#: which is the whole test. "fake" is deliberately NOT here: it is a token
#: the shown-failing demonstration plants with, and a guard that allows its
#: own probe cannot be shown failing.
SYNTHETIC_SLUG_TOKENS = (
    "test",
    "someone",
    "somebody",
    "example",
    "anonymous",
    "a-real-person",
    "another-person",
    "candidate",
    "placeholder",
    "redacted",  # WIDENED: the capture scripts rewrite every contact to
                 # /in/redacted-contact-<n> before anything is written down.
)

#: Known-fake slugs that carry no synthetic token. Each repo adds its own
#: here as they appear. Empty is correct until one does.
SYNTHETIC_SLUGS = frozenset()


def _has_synthetic_token(text: str) -> bool:
    lowered = text.lower()
    return any(token in lowered for token in SYNTHETIC_SLUG_TOKENS)


def _slug_allowed(slug: str) -> bool:
    if slug in SYNTHETIC_SLUGS:
        return True
    return _has_synthetic_token(slug)


def test_no_personal_linkedin_slugs():
    """No /in/<slug> that could name a real person."""
    hits = []
    for rel, lineno, line in _iter_lines():
        for match in LINKEDIN_SLUG.finditer(line):
            slug = match.group(1)
            if _slug_allowed(slug):
                continue
            hits.append("%s:%d  LINKEDIN-SLUG  %s" % (rel, lineno, _redact(slug)))
    assert not hits, (
        "LinkedIn profile slugs that could name a real person are tracked "
        "in this repo. Rewrite the DATA to a slug carrying a synthetic "
        "token.\n%s" % _report(hits)
    )


# --------------------------------------------------------------------------
# Check 4 -- LinkedIn numeric company id and member URN
# --------------------------------------------------------------------------

LINKEDIN_COMPANY_ID = re.compile(r"(?:/company/|currentCompany=|companyId=)(\d{3,})")
LINKEDIN_MEMBER_TOKEN = re.compile(r"ACoAA[A-Za-z0-9_\-]{10,}")
LINKEDIN_URN_ID = re.compile(r"urn:li:[a-zA-Z]+:\(?(\d{6,})")

#: Known-fake LinkedIn ids. Each repo adds its OWN known-fake ids here as
#: they appear -- an id is only ever admitted after someone confirms it
#: names nothing. There are none in this repo today, so the empty set is
#: correct and the check is live rather than decorative.
SYNTHETIC_LINKEDIN_IDS = frozenset()


def test_no_linkedin_numeric_ids():
    """No opaque LinkedIn company id, member token, or numeric URN."""
    hits = []
    for rel, lineno, line in _iter_lines():
        for name, pattern, group in (
            ("LI-COMPANY-ID", LINKEDIN_COMPANY_ID, 1),
            ("LI-MEMBER-TOKEN", LINKEDIN_MEMBER_TOKEN, 0),
            ("LI-URN-ID", LINKEDIN_URN_ID, 1),
        ):
            for match in pattern.finditer(line):
                value = match.group(group)
                if value in SYNTHETIC_LINKEDIN_IDS:
                    continue
                hits.append("%s:%d  %s  %s" % (rel, lineno, name, _redact(value)))
    assert not hits, (
        "Opaque LinkedIn identifiers are tracked in this repo. They name a "
        "real company or member even though they read as noise. Remove the "
        "DATA, or add the id to SYNTHETIC_LINKEDIN_IDS only once it is "
        "confirmed invented.\n%s" % _report(hits)
    )


# --------------------------------------------------------------------------
# Check 5 -- opaque credential and session-token shapes
# --------------------------------------------------------------------------

JWT_SHAPE = re.compile(r"eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{5,}")
COOKIE_ASSIGNMENT = re.compile(
    r"(li_at|JSESSIONID|li_rm|bcookie|bscookie|nauk_at|sessionid|csrftoken)"
    r"\s*[=:]\s*[\"']?(\S{20,})"
)

#: A value carrying one of these is a stand-in, not a credential.
PLACEHOLDER_MARKERS = (
    "xxx",
    "dummy",
    "fake",
    "redacted",
    "placeholder",
    "<",
    "...",
)


def _credential_allowed(value: str) -> bool:
    lowered = value.lower()
    if any(marker in lowered for marker in PLACEHOLDER_MARKERS):
        return True
    stripped = value.strip("\"'")
    return bool(stripped) and len(set(stripped)) == 1


def test_no_credential_or_session_tokens():
    """No JWT and no session-cookie assignment carrying a live value."""
    hits = []
    for rel, lineno, line in _iter_lines(skip=_is_pins_or_lock):
        for match in JWT_SHAPE.finditer(line):
            value = match.group(0)
            if _credential_allowed(value):
                continue
            hits.append("%s:%d  JWT  %s" % (rel, lineno, _redact(value)))
        for match in COOKIE_ASSIGNMENT.finditer(line):
            value = match.group(2)
            if _credential_allowed(value):
                continue
            hits.append(
                "%s:%d  COOKIE[%s]  %s"
                % (rel, lineno, match.group(1), _fingerprint(value))
            )
    assert not hits, (
        "Credential-shaped values are tracked in this repo. Rotate the "
        "secret first, then replace the DATA with an obvious "
        "placeholder.\n%s" % _report(hits)
    )


# --------------------------------------------------------------------------
# Check 6 -- mapping table / de-anonymisation key
# --------------------------------------------------------------------------
#
# The one that would have caught the incident. It is STRUCTURAL, not
# keyword-driven: a de-anonymisation key is recognised by being a table of
# pairs whose LEFT column holds real-value-shaped strings, whatever it is
# called. The variable name only lowers the threshold; it never carries the
# finding on its own.

BARE_INT_4PLUS = re.compile(r"^\d{4,}$")
TITLECASE_WORDS = re.compile(r"^[A-Z][a-z'\-]+(?: [A-Z][a-z'\-]+)+$")
LOWER_SLUG_2SEG = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)+$")

SUSPICIOUS_TABLE_NAME = re.compile(
    r"(?i)(mask|map|subst|replac|anon|scrub|sanit|real|alias|rename"
    r"|forbidden|slugs|operator|posting|employers)"
)

MIN_PAIRS_STRUCTURAL = 3
MIN_REAL_LEFTS_STRUCTURAL = 3
MIN_PAIRS_BY_NAME = 5
#: WIDENED -- the name-triggered rule additionally requires at least one
#: real-value-shaped left. Without it the rule fires on ordinary schema
#: maps whose left column is a field NAME rather than a value (a scrubber's
#: field -> placeholder map, a shared-key -> local-field map). Those hold no
#: values at all, so they cannot be a de-anonymisation key. A table with the
#: same suspicious name that DOES hold one real-shaped value still fires,
#: two pairs below the structural threshold.
MIN_REAL_LEFTS_BY_NAME = 1


def _shape_of_real_value(text: str):
    """Name the PII/proper-noun shape of `text`, or None if it looks fake.

    Order matters. An explicit PII shape that the allowlists accept returns
    None immediately: an allowlisted test number must not fall through and
    be re-flagged as a bare integer.
    """
    value = text.strip()
    if not value:
        return None
    if _has_synthetic_token(value):
        return None

    matched_pii = False
    for shape, pattern, allowed in (
        ("email shape", EMAIL_SHAPE, lambda m: _email_allowed(m.group(0))),
        ("phone shape", PHONE_IN_SHAPE, lambda m: _phone_allowed(m.group(0))),
        ("E.164 shape", PHONE_E164_SHAPE, lambda m: _phone_allowed(m.group(0))),
        ("linkedin slug", LINKEDIN_SLUG, lambda m: _slug_allowed(m.group(1))),
        (
            "linkedin company id",
            LINKEDIN_COMPANY_ID,
            lambda m: m.group(1) in SYNTHETIC_LINKEDIN_IDS,
        ),
        (
            "linkedin member token",
            LINKEDIN_MEMBER_TOKEN,
            lambda m: m.group(0) in SYNTHETIC_LINKEDIN_IDS,
        ),
        (
            "linkedin urn id",
            LINKEDIN_URN_ID,
            lambda m: m.group(1) in SYNTHETIC_LINKEDIN_IDS,
        ),
        ("jwt", JWT_SHAPE, lambda m: _credential_allowed(m.group(0))),
        (
            "session cookie",
            COOKIE_ASSIGNMENT,
            lambda m: _credential_allowed(m.group(2)),
        ),
    ):
        match = pattern.search(value)
        if match is None:
            continue
        matched_pii = True
        if not allowed(match):
            return shape
    if matched_pii:
        return None

    if BARE_INT_4PLUS.match(value):
        return "bare integer"
    if TITLECASE_WORDS.match(value):
        return "Titlecase words"
    if LOWER_SLUG_2SEG.match(value):
        return "lowercase slug"
    return None


def _string_pairs(node):
    """String (left, right) pairs from a list/tuple of tuples, or a dict."""
    pairs = []
    if isinstance(node, (ast.List, ast.Tuple)):
        for element in node.elts:
            if not isinstance(element, (ast.Tuple, ast.List)):
                continue
            if len(element.elts) < 2:
                continue
            left, right = element.elts[0], element.elts[1]
            if (
                isinstance(left, ast.Constant)
                and isinstance(left.value, str)
                and isinstance(right, ast.Constant)
                and isinstance(right.value, str)
            ):
                pairs.append((left.value, right.value))
    elif isinstance(node, ast.Dict):
        for key, value in zip(node.keys, node.values):
            if (
                isinstance(key, ast.Constant)
                and isinstance(key.value, str)
                and isinstance(value, ast.Constant)
                and isinstance(value.value, str)
            ):
                pairs.append((key.value, value.value))
    return pairs


def _assignments(scope):
    """(name, value_node, lineno) for each assignment directly in `scope`."""
    for statement in scope.body:
        if isinstance(statement, ast.Assign):
            targets = statement.targets
        elif isinstance(statement, ast.AnnAssign) and statement.value is not None:
            targets = [statement.target]
        else:
            continue
        names = [t.id for t in targets if isinstance(t, ast.Name)]
        yield (names[0] if names else "<unnamed>"), statement.value, statement.lineno


def test_no_mapping_table_of_real_values():
    """No committed pair table that reverses a redaction.

    Reports the variable name, its location, and the pair count only. The
    values are never printed: printing them into a CI log recreates exactly
    the leak this check exists to prevent.
    """
    hits = []
    for rel, _path, text in _tracked_text_files():
        if not rel.lower().endswith(".py"):
            continue
        try:
            tree = ast.parse(text, filename=rel)
        except SyntaxError:
            continue

        scopes = [(tree, True)]
        scopes += [
            (node, False) for node in ast.walk(tree) if isinstance(node, ast.ClassDef)
        ]
        for scope, is_module_level in scopes:
            for name, value, lineno in _assignments(scope):
                pairs = _string_pairs(value)
                if not pairs:
                    continue
                shapes = [
                    shape
                    for shape in (_shape_of_real_value(left) for left, _ in pairs)
                    if shape is not None
                ]
                structural = (
                    len(pairs) >= MIN_PAIRS_STRUCTURAL
                    and len(shapes) >= MIN_REAL_LEFTS_STRUCTURAL
                )
                by_name = (
                    is_module_level
                    and len(pairs) >= MIN_PAIRS_BY_NAME
                    and len(shapes) >= MIN_REAL_LEFTS_BY_NAME
                    and bool(SUSPICIOUS_TABLE_NAME.search(name))
                )
                if not (structural or by_name):
                    continue
                sample = ", ".join(sorted({"<%s>" % shape for shape in shapes})[:3])
                hits.append(
                    "%s:%d  MAPPING-TABLE  %s  pairs=%d  real_shaped_lefts=%d"
                    "  rule=%s  left-column shapes: %s"
                    % (
                        rel,
                        lineno,
                        name,
                        len(pairs),
                        len(shapes),
                        "structural" if structural else "suspicious-name",
                        sample,
                    )
                )
    assert not hits, (
        "A pair table whose left column holds real-value-shaped strings is "
        "tracked in this repo. That is a de-anonymisation key: it reverses "
        "whatever redaction was applied elsewhere. Delete the TABLE. Do not "
        "add its values to any allowlist here.\n%s" % _report(hits)
    )


# --------------------------------------------------------------------------
# Check N -- this machine's filesystem layout, in a COMMITTED file
#
# ADDED 2026-08-31, AND THE REASON IT DID NOT EXIST IS THE FINDING. This
# repository has had `tests/test_path_hygiene.py` for over a week, and that
# file is thorough -- but its subject is a TOOL RESULT at runtime. It walks
# payloads. It has never read a tracked file. The module you are reading
# walks every tracked file and, until today, hunted email, phone, LinkedIn
# handles, credentials and account ids: fifteen shapes, none of them a
# filesystem path.
#
# So the two guards between them left an exact hole -- runtime payloads
# checked for paths, committed files checked for everything BUT paths -- and
# a sweep on 2026-08-31 found the operator's given name sitting in a
# drive-rooted absolute path in tracked files here, in the sibling Instahyre
# repository, and in Naukri. All three repositories are PUBLIC.
#
# Naukri is the instructive one. It ALONE had a committed-file path rule, and
# that rule was green over its own four leaks, because it was written
# `[\\/]` -- exactly ONE separator, with the captured segment starting on the
# next character. On the DOUBLED spelling the next character is another
# separator, so the rule did not match. A JSON config, a Python string
# literal, a docstring quoting either, and repr() of any Windows path all
# write the doubled form. Every leak found that day was the doubled form.
#
# Hence the two rules below this comment block: the separator run is `+`, and
# a control asserts BOTH spellings on every rule, built from chr(92) so that
# no quoting layer between this file and the regex engine can weaken it
# without the control going red.
# --------------------------------------------------------------------------

#: ONE BACKSLASH, spelled rather than escaped. Every separator in the three
#: rules below is built from this at import time, so the source of this file
#: contains no literal doubled backslash inside a pattern at all. That is
#: deliberate and it is the lesson of the defect: a heredoc, an editor or a
#: patch tool that collapses a doubled backslash silently turns
#: backslash-or-slash into slash-only, every test keeps passing, and the
#: Windows half of the rule is dead. Building it here means the collapse has
#: nothing to collapse.
BACKSLASH = chr(92)

#: One or more separators, either spelling. THE `+` IS THE WHOLE FIX -- see
#: the comment block above, and
#: :func:`test_every_path_rule_sees_the_doubled_separator_spelling`.
_SEP_RUN = "[" + BACKSLASH + BACKSLASH + "/]+"

#: A Windows per-user directory: the account name is the leaking value.
WINDOWS_USER_PATH = re.compile(
    "[A-Za-z]:" + _SEP_RUN + "Users" + _SEP_RUN + "([A-Za-z0-9._-]{2,})"
)

#: A drive rooted straight at a segment that is not generic -- the form a
#: checkout under a person's own name takes, e.g. a drive root named after
#: its owner. This is a SEPARATE rule from the one above because that one
#: needs a literal `Users` segment and this form has none: the leak sits one
#: segment to the LEFT of where a user-path rule looks. That gap is not
#: hypothetical -- it is where every hit in this repository was found.
#:
#: The lookbehind is load-bearing: a drive letter is ONE character, and
#: without it this matches the "s:/" inside "https://" and reports every
#: correct URL in the repository as a leak.
DRIVE_ROOT_PATH = re.compile(
    "(?<![A-Za-z0-9_])[A-Za-z]:" + _SEP_RUN + "([A-Za-z0-9_.-]{2,})"
)

#: The POSIX home form. The lookbehind excludes ":" so a drive-letter path is
#: counted once rather than twice, excludes word characters so the prose
#: "anchored/home/tail" stops reading as a home directory, and excludes "/"
#: so that widening the run to "/+" cannot let the rule start on the SECOND
#: slash of "https://home/x" -- past the colon it was written to block.
POSIX_HOME_PATH = re.compile(
    "(?<![A-Za-z0-9_:/])/+(?:home|Users)/+([A-Za-z0-9._-]{2,})"
)

#: Drive roots that name a PLACE rather than a person. MEASURED before this
#: allowlist was written: the whole tracked tree contains a handful of
#: distinct drive-path roots and every one of them is already generic, so
#: this set is small, auditable, and holds ONLY generic tokens. No real value
#: is named here -- it is an allowlist of the synthetic, never a blocklist of
#: the real, because a committed list of real values is itself the
#: de-anonymising key this module exists to refuse.
GENERIC_DRIVE_ROOTS = frozenset(
    {
        "users",            # handed to WINDOWS_USER_PATH, which reads the NEXT segment
        "windows",
        "programdata",
        "program",          # "Program Files" truncates at the space
        "workspace",
        "claude-workspace",
        "dev-cache",
        "temp",
        "tmp",
        "repo",
        "opt",              # a Z:/opt test-corpus literal
        "leak",             # a D:/leak test-corpus literal -- names a defect, not a person
        "out.csv",          # a test corpus literal
    }
)

#: Account names in an absolute path that identify nobody. "runner" is the
#: GitHub Actions account and appears in this repo's CI-path reasoning.
PLACEHOLDER_ACCOUNTS = frozenset(
    {
        "you", "user", "username", "me", "someone", "somebody", "anonymous",
        "test", "runner", "windows", "public", "default", "home", "root",
    }
)
PLACEHOLDER_ACCOUNT_TOKENS = ("user", "test", "example", "placeholder", "runner")


def _segment_is_documentation(segment: str) -> bool:
    """An ellipsis or an angle-bracket names nobody -- it elides a name.

    Both spellings appear in this repository's own prose, and neither is a
    valid Windows account name or directory name, so admitting them costs no
    coverage of anything real.
    """
    return "." * 3 in segment or "<" in segment


def _account_allowed(segment: str) -> bool:
    account = segment.lower().strip("._-")
    if account in PLACEHOLDER_ACCOUNTS:
        return True
    if any(token in account for token in PLACEHOLDER_ACCOUNT_TOKENS):
        return True
    return _segment_is_documentation(segment)


def _drive_root_allowed(segment: str) -> bool:
    if segment.lower() in GENERIC_DRIVE_ROOTS:
        return True
    if any(token in segment.lower() for token in PLACEHOLDER_ACCOUNT_TOKENS):
        return True
    return _segment_is_documentation(segment)


#: (name, rule, subject builder, the segment the subject names, predicate).
#:
#: EVERY RULE ABOVE, REGISTERED. The controls below iterate this tuple rather
#: than a hand-written list, so a path rule added next year is covered by both
#: of them the moment it is registered here -- rather than on the day somebody
#: remembers to extend a test. The builder takes the Windows separator RUN and
#: the POSIX separator RUN, so one subject serves both spellings and the two
#: cannot drift apart. Every account named here is invented.
PATH_SHAPES = (
    (
        "WINDOWS_USER_PATH",
        WINDOWS_USER_PATH,
        lambda w, p: "C:" + w + "Users" + w + "Jmorrissey" + w + "x.json",
        "Jmorrissey",
        _account_allowed,
    ),
    (
        "DRIVE_ROOT_PATH",
        DRIVE_ROOT_PATH,
        lambda w, p: "D:" + w + "Given" + w + "projects",
        "Given",
        _drive_root_allowed,
    ),
    (
        "POSIX_HOME_PATH",
        POSIX_HOME_PATH,
        lambda w, p: p + "home" + p + "jmorrissey" + p + ".config",
        "jmorrissey",
        _account_allowed,
    ),
)


def test_no_tracked_file_publishes_this_machines_layout():
    """No committed file may carry an absolute path naming a real person.

    This is the check the repository did not have. See the comment block
    above for what that cost.
    """
    hits = []
    for rel, lineno, line in _iter_lines(skip=_is_pins_or_lock):
        for name, rule, _subject, _expected, allowed in PATH_SHAPES:
            for match in rule.finditer(line):
                segment = match.group(1)
                if allowed(segment):
                    continue
                hits.append(
                    "%s:%d  %s  %s  (segment %s is not generic/synthetic)"
                    % (rel, lineno, name, _redact(match.group(0)),
                       _redact(segment))
                )
    assert not hits, (
        "Absolute local paths naming a real account or a real given name are "
        "tracked in this repo, which is public. Replace the DATA -- a "
        "synthetic segment keeps every meaning a path example has, and a "
        "hygiene fixture that proves itself by carrying the thing it forbids "
        "is self-refuting. Do NOT add the real value to an allowlist here; "
        "that rebuilds the key.\n%s" % _report(hits)
    )


def test_every_path_rule_sees_the_doubled_separator_spelling():
    """THE DEFECT THAT LET THIS CLASS SHIP, PINNED SO IT CANNOT RETURN.

    Asserting both separator CHARACTERS is not enough and that is exactly how
    the sibling Naukri guard stayed green over its own leaks: it asserted
    backslash and forward slash, never the separator COUNT. A rule reading
    one separator cannot match the doubled spelling, and the doubled spelling
    is the COMMON one in committed code -- a JSON config, a Python literal, a
    docstring quoting either, repr() of any Windows path.

    Built from chr(92), so no quoting layer can weaken the subject without
    this test noticing.
    """
    for name, rule, subject, expected, _allowed in PATH_SHAPES:
        single = subject(BACKSLASH, "/")
        doubled = subject(BACKSLASH + BACKSLASH, "//")

        assert single != doubled, name + ": the two spellings are identical"

        got_single = rule.search(single)
        assert got_single, name + " cannot see the SINGLE-separator spelling"
        assert got_single.group(1) == expected, (
            name + " matched the single form but captured "
            + repr(got_single.group(1)) + " rather than the segment"
        )

        got_doubled = rule.search(doubled)
        assert got_doubled, (
            name + " IS BLIND TO THE DOUBLED-SEPARATOR SPELLING -- the exact "
            "defect that let this class ship green across three public repos"
        )
        assert got_doubled.group(1) == expected, (
            name + " matched the doubled form but captured "
            + repr(got_doubled.group(1)) + " rather than the segment, so it "
            "would report a separator as the leaking value"
        )


def test_the_doubled_separator_control_fails_on_the_narrow_rule__CONTROL():
    """THE MUTATION, EXECUTED. A check never seen to fail certifies nothing.

    The narrow rule is DERIVED from the shipped one by undoing exactly the
    edit that fixed it, so this cannot drift from what it claims to test and
    it reproduces the real historical defect rather than an imitation of it.
    If a future rewrite makes this test fail, the widening has been undone.
    """
    for name, rule, subject, _expected, _allowed in PATH_SHAPES:
        narrow = re.compile(rule.pattern.replace("]+", "]").replace("/+", "/"))
        assert narrow.pattern != rule.pattern, (
            name + ": the mutation changed nothing, so this control is inert "
            "-- the separator run is no longer spelled the way it was fixed"
        )
        assert narrow.search(subject(BACKSLASH, "/")), (
            name + ": the narrow rule cannot see the SINGLE form either, so "
            "this control would pass for the wrong reason"
        )
        assert not narrow.search(subject(BACKSLASH + BACKSLASH, "//")), (
            name + ": the narrow rule now sees the doubled spelling, so the "
            "shipped rule's '+' is not what makes the difference and the "
            "control above proves nothing"
        )


#: Shape-valid layout leaks, every one INVENTED, in BOTH separator spellings.
#: A control that needs a real identifier has the same defect as the fixture
#: it is guarding.
_PLANTED_PATHS = (
    "traceback from C:" + BACKSLASH + "Users" + BACKSLASH + "Jmorrissey"
    + BACKSLASH + "AppData",
    "traceback from C:" + BACKSLASH * 2 + "Users" + BACKSLASH * 2
    + "Jmorrissey" + BACKSLASH * 2 + "AppData",
    "traceback from C:/Users/Jmorrissey/AppData",
    "the checkout is at D:" + BACKSLASH + "Given" + BACKSLASH + "projects",
    "the checkout is at D:" + BACKSLASH * 2 + "Given" + BACKSLASH * 2
    + "projects",
    "wrote /home/jmorrissey/.config/state.json",
    "wrote //home//jmorrissey//.config//state.json",
)

#: The allowlisted equivalent of each plant -- already synthetic, and it must
#: stay QUIET. THE CONTROL FOR THE CONTROLS: without it every assertion above
#: would also pass on a rule that simply refuses everything, which would make
#: the allowlists meaningless and this module unmaintainable.
_BENIGN_PATHS = (
    "scrubbed to C:" + BACKSLASH + "Users" + BACKSLASH + "runner"
    + BACKSLASH + "work",
    "scrubbed to C:" + BACKSLASH * 2 + "Users" + BACKSLASH * 2 + "runner",
    "could not append to C:" + BACKSLASH * 2 + "Users" + BACKSLASH * 2
    + "..." + BACKSLASH * 2 + "history.jsonl",
    "lock held under C:" + BACKSLASH * 2 + "Users" + BACKSLASH * 2 + "<name>",
    "the tree is at D:" + BACKSLASH * 2 + "workspace" + BACKSLASH * 2
    + "projects",
    "mock returns /home/user/some/file",
    "the anchored/home/tail form keeps its separator",
    "the docs live at https://home/getting-started",
    "the API route is https://platform.example.com/talent/x",
)


def _layout_hits(text):
    found = []
    for name, rule, _subject, _expected, allowed in PATH_SHAPES:
        for match in rule.finditer(text):
            if not allowed(match.group(1)):
                found.append((name, match.group(1)))
    return found


def test_the_layout_check_fires_on_every_planted_path__CONTROL():
    """Each plant, driven. An assertion of ABSENCE is only worth the
    demonstration that the detector behind it can be made to fire."""
    for planted in _PLANTED_PATHS:
        assert _layout_hits(planted), (
            "a planted absolute layout was NOT caught, so the corresponding "
            "absence assertion certifies nothing: " + repr(planted)
        )


def test_the_layout_check_stays_quiet_on_synthetic_paths__CONTROL():
    """And the reverse, or a rule that refuses everything would pass above."""
    for benign in _BENIGN_PATHS:
        assert not _layout_hits(benign), (
            "an already-synthetic path was reported as a leak, which is how "
            "a guard gets narrowed into uselessness: " + repr(benign)
        )
