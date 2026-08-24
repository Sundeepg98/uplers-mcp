"""Human-readable identity census over EVERY blob in the whole git history.

WHY THIS EXISTS
---------------
This repository is a candidate for being made public and permanent. Publishing
is a one-way door: a value that reaches the public remote can never be recalled,
and rewriting history does not recall a value someone already fetched. So before
that door is opened, somebody has to know exactly what identity-shaped data the
repository CONTAINS -- not what its guard happens to test, and not what HEAD
happens to show. History is the population, HEAD is one sample of it.

WHAT IT MEASURES, AND WHAT IT DELIBERATELY DOES NOT
---------------------------------------------------
It measures HUMAN-READABLE identity shapes: addresses, phone-shaped runs,
personal profile slugs, personal-looking URLs, at-handles, and full personal
names sitting beside a role word. The OPAQUE-TOKEN class (talent ids, thread
ids, actor ids, session values, signed URLs) is a separate census and is NOT
duplicated here.

THE OUTPUT RULE, WHICH IS THE POINT OF THE WHOLE SCRIPT
-------------------------------------------------------
This script NEVER writes a found value into its report. Not redacted, not
truncated, not first-and-last character. A value reproduced in a report is a
fresh copy of the thing being removed, and the report outlives the removal.
Every finding is addressed by a synthetic label (A1, B2, ...) plus a SHA-256
prefix handle, and every count is a count.

The one exception is `--triage`, which prints residual values to STDOUT for a
human to classify. It writes nothing, it is never the report, and its output
belongs in a scratch location that is not this repository.

This script also carries NO real value as a literal. Owner identity is DERIVED
at runtime from the commit author fields already present in the history (which
are public the moment the repo is), never hardcoded. A hardcoded list of real
strings would itself be a de-anonymisation key -- the exact defect this whole
line of work exists to remove.

POPULATION
----------
`git rev-list --objects --all` in a MIRROR of the published remote, which is the
authority on what a fetcher receives. Not a glob, not `git ls-files`, not a
directory walk. Binary blobs are excluded by CONTENT SNIFF (a NUL byte in the
leading window), never by file extension, because an extension is a claim and
content is evidence.

BOUNDARIES
----------
Every numeric shape uses TOKEN boundaries, `(?<![A-Za-z0-9_])`, never digit-only
boundaries. A digit-only boundary still matches a digit run sitting inside a hex
hash or an alphanumeric id, which manufactures findings. The digit-boundary
variant is still evaluated, and the difference is reported as a delta so that
the stricter boundary cannot silently hide anything.

WHAT NO CHECK HERE CAN DO
--------------------------
A personal NAME has no shape. The NAME-NEAR-ROLE check is a proximity heuristic,
not a detector: it finds titlecase runs near role vocabulary and will both miss
names and over-fire on product nouns. A green run of this script is NOT evidence
that no name is present. Names need a human.

USAGE
-----
  python publish_identity_census.py --mirror <path-to-mirror> --out <report.md>
  python publish_identity_census.py --control <dir-of-planted-files>
  python publish_identity_census.py --mirror <path> --triage
"""

from __future__ import annotations

import argparse
import collections
import hashlib
import json
import os
import re
import subprocess
import threading
import sys

# --------------------------------------------------------------------------
# Self-exclusion. The scanner and its report both contain the shapes they
# hunt; scanning either one manufactures findings out of the instrument.
# --------------------------------------------------------------------------

EXCLUDED_PATH_SUFFIXES = (
    "scripts/publish_identity_census.py",
    "_audit/_slices/_slice-publish-identity-census.md",
)

#: Dependency pins and lock files are dense with base16/base64 hashes that
#: collide with several shapes below. A hash is not a person.
LOCK_NAMES = frozenset(
    {"package-lock.json", "poetry.lock", "uv.lock", "cargo.lock", "yarn.lock"}
)

#: A 40-hex git SHA contains ten-digit runs that begin 6-9.
GIT_SHA40 = re.compile(r"(?<![0-9a-fA-F])[0-9a-f]{40}(?![0-9a-fA-F])")

BINARY_SNIFF_WINDOW = 8192


# --------------------------------------------------------------------------
# Shapes
# --------------------------------------------------------------------------

TOK = r"(?<![A-Za-z0-9_])"
KOT = r"(?![A-Za-z0-9_])"

# Check 1 -- email
EMAIL_SHAPE = re.compile(
    r"(?<![A-Za-z0-9._%+-])[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,24}(?![A-Za-z0-9-])"
)

# Check 2 -- phone. TOKEN boundaries, per the binding law.
PHONE_IN_SHAPE = re.compile(TOK + r"(?:\+?91[-\s]?)?[6-9]\d{9}" + KOT)
PHONE_E164_SHAPE = re.compile(TOK + r"\+\d{1,3}[-\s]?\d{6,12}" + KOT)
# The looser digit-boundary variant from the guard spec, evaluated only to
# measure what the stricter boundary excludes. Never reported as a finding.
PHONE_IN_DIGITBOUND = re.compile(r"(?<![\d.])(?:\+?91[-\s]?)?[6-9]\d{9}(?![\d.])")

# Check 3 -- personal profile slug
LINKEDIN_SLUG = re.compile(r"(?:linkedin\.com)?/in/([A-Za-z0-9\-_%]{3,})")

# Check 4 -- LinkedIn numeric / opaque identity ids
LINKEDIN_COMPANY_ID = re.compile(r"(?:/company/|currentCompany=|companyId=)(\d{3,})")
LINKEDIN_MEMBER_TOKEN = re.compile(r"ACoAA[A-Za-z0-9_\-]{10,}")
LINKEDIN_URN_ID = re.compile(r"urn:li:[a-zA-Z]+:\(?(\d{6,})")

# Check 5 -- credential / session shapes
JWT_SHAPE = re.compile(r"eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{5,}")
COOKIE_ASSIGNMENT = re.compile(
    r"(li_at|JSESSIONID|li_rm|bcookie|bscookie|nauk_at|sessionid|csrftoken"
    r"|remember_token|_uplers_session|access_token|refresh_token)"
    r"\s*[=:]\s*[\"']?(\S{20,})"
)

# Extra 6 -- personal name beside a role word.
ROLE_WORD = re.compile(
    r"(?i)(?<![A-Za-z0-9_])("
    r"recruiter|recruiters|hr|hiring[_ -]?manager|employee|employees"
    r"|employee_name|contact|contact_name|contact_person|person|poc"
    r"|interviewer|referrer|candidate_name|owner_name|full_name"
    r"|first_name|last_name|posted_by|created_by|assigned_to|talent_advisor"
    r"|account_manager|spoc"
    r")(?![A-Za-z0-9_])"
)
#: Two-to-four titlecase words. Apostrophes and hyphens allowed inside.
TITLECASE_RUN = re.compile(
    r"(?<![A-Za-z0-9_'\-])([A-Z][a-z'\-]{1,19}(?: [A-Z][a-z'\-]{1,19}){1,3})"
    r"(?![A-Za-z0-9_'\-])"
)

#: Extra 6b -- SIGN-OFF NAME. Added after a hand read found three third-party
#: given names that every shape check passed over. A given name has no lexical
#: shape, but a sign-off has a POSITIONAL one: a closing word, then a line
#: holding one or two capitalised words and nothing else. That is a shape, and
#: it is the only handle a lone first name offers.
SIGNOFF_LINE = re.compile(
    r"(?i)(?:^|[\r\n]|\\r\\n|\\n)\s*"
    r"(?:regards|warm regards|best regards|best|thanks|thank you|sincerely"
    r"|cheers|yours truly|kind regards|br)\s*[,.]?\s*"
    r"(?:[\r\n]|\\r\\n|\\n)\s*"
    r"([A-Z][a-zA-Z'\-]{1,19}(?: [A-Z][a-zA-Z'\-]{1,19})?)\s*"
    r"(?=[\r\n]|\\r\\n|\\n|$)"
)

#: Extra 6c -- NANP / US-style phone. Added for the same reason: the two phone
#: shapes inherited from the guard spec assume an Indian mobile or a leading
#: plus sign, so a US number written NNN-NNN-NNNN was invisible to both.
PHONE_NANP_SHAPE = re.compile(
    TOK + r"(?:\+?1[-.\s])?\(?[2-9]\d{2}\)?[-.\s]\d{3}[-.\s]\d{4}" + KOT
)

# Extra 7 -- at-handle that is not part of an email address
AT_HANDLE = re.compile(r"(?<![A-Za-z0-9._%+\-@])@([A-Za-z0-9._\-]{3,30})(?![A-Za-z0-9._\-@])")

# Extra 8 -- URL that points at a PERSON rather than a company
PERSON_URL = re.compile(
    r"(?i)\b(?:https?://)?(?:www\.)?("
    r"github\.com/[A-Za-z0-9\-]{2,39}"
    r"|gitlab\.com/[A-Za-z0-9\-_.]{2,39}"
    r"|twitter\.com/[A-Za-z0-9_]{2,15}"
    r"|x\.com/[A-Za-z0-9_]{2,15}"
    r"|calendly\.com/[A-Za-z0-9\-_]{2,40}"
    r"|topmate\.io/[A-Za-z0-9\-_]{2,40}"
    r"|instagram\.com/[A-Za-z0-9._]{2,30}"
    r"|facebook\.com/[A-Za-z0-9.]{5,50}"
    r"|medium\.com/@[A-Za-z0-9._\-]{2,40}"
    r"|t\.me/[A-Za-z0-9_]{5,32}"
    r"|wa\.me/\d{8,15}"
    r")"
)
MAILTO = re.compile(r"(?i)mailto:([A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,24})")


# --------------------------------------------------------------------------
# Synthetic recognisers -- allowlist the FAKE, never blocklist the real
# --------------------------------------------------------------------------

RESERVED_EXACT_DOMAINS = frozenset(
    {"example.com", "example.org", "example.net", "localhost", "test", "invalid"}
)
RESERVED_DOMAIN_SUFFIXES = (
    ".invalid",
    ".example.com",
    ".example.org",
    ".example.net",
    ".test",
    ".localhost",
)
#: Single-letter regex-probe domains used by unit tests. Cannot belong to
#: anybody in the sense that matters: no test here ever sends to them.
STUB_EMAIL_DOMAINS = frozenset({"x.com", "b.co", "a.co", "example.invalid.co"})

CLASSIC_TEST_NUMBERS = frozenset(
    {"9876543210", "1000000000", "0000000000", "1234567890", "9999999999"}
)

SYNTHETIC_TOKENS = (
    "test", "someone", "somebody", "example", "anonymous", "a-real-person",
    "another-person", "candidate", "placeholder", "redacted", "sample",
    "dummy", "specimen", "fixture", "synthetic", "invented", "notreal",
    "john-doe", "jane-doe", "johndoe", "janedoe", "foo", "bar", "xxx",
)

PLACEHOLDER_MARKERS = ("xxx", "dummy", "fake", "redacted", "placeholder", "<", "...")

#: Handles/paths that name a project or org, not a person.
NON_PERSON_URL_TOKENS = (
    "actions", "features", "about", "pricing", "marketplace", "orgs",
    "settings", "login", "join", "explore", "topics", "trending",
    "microsoft", "python", "pypa", "psf", "docker", "google", "modelcontextprotocol",
    "anthropics", "pytest-dev", "jlowin", "encode", "aio-libs", "uplers",
)


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8", "surrogateescape")).hexdigest()[:12]


def _email_domain(addr: str) -> str:
    return addr.rsplit("@", 1)[-1].rstrip(".").lower()


def _email_local(addr: str) -> str:
    return addr.rsplit("@", 1)[0].lower()


def _email_is_synthetic(addr: str) -> bool:
    domain = _email_domain(addr)
    if domain in RESERVED_EXACT_DOMAINS or domain in STUB_EMAIL_DOMAINS:
        return True
    if domain.endswith(RESERVED_DOMAIN_SUFFIXES):
        return True
    return False


def _has_synthetic_token(text: str) -> bool:
    lowered = text.lower()
    return any(tok in lowered for tok in SYNTHETIC_TOKENS)


def _phone_is_synthetic(text: str) -> bool:
    digits = re.sub(r"\D", "", text)
    if not digits:
        return True
    candidates = {digits}
    for cc in (1, 2, 3):
        if len(digits) > cc:
            candidates.add(digits[cc:])
    for cand in candidates:
        if cand and set(cand) == {"0"}:
            return True
        if cand in CLASSIC_TEST_NUMBERS:
            return True
        # A strictly ascending or descending digit run is a keyboard walk.
        if len(cand) >= 8:
            asc = all(ord(b) - ord(a) == 1 for a, b in zip(cand, cand[1:]))
            desc = all(ord(a) - ord(b) == 1 for a, b in zip(cand, cand[1:]))
            if asc or desc:
                return True
    return False


def _credential_is_placeholder(value: str) -> bool:
    lowered = value.lower()
    if any(m in lowered for m in PLACEHOLDER_MARKERS):
        return True
    stripped = value.strip("\"'")
    return bool(stripped) and len(set(stripped)) == 1


# --------------------------------------------------------------------------
# Git plumbing
# --------------------------------------------------------------------------


def _git(mirror: str, *args: str) -> str:
    proc = subprocess.run(
        ["git", "--git-dir", mirror, *args],
        capture_output=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            "git %s failed in %s (exit %d): %s"
            % (" ".join(args), mirror, proc.returncode,
               proc.stderr.decode("utf-8", "replace"))
        )
    return proc.stdout.decode("utf-8", "surrogateescape")


def enumerate_population(mirror: str):
    """Return (blob_paths, blob_commits, head_blobs, commit_count).

    blob_paths   : blob sha -> set of every path it has ever occupied
    blob_commits : blob sha -> set of commits whose tree contains it
    head_blobs   : set of blob shas reachable from the single head
    """
    commits = [c for c in _git(mirror, "rev-list", "--all").split() if c]
    blob_commits = collections.defaultdict(set)
    blob_paths = collections.defaultdict(set)
    for commit in commits:
        for line in _git(mirror, "ls-tree", "-r", "--full-tree", commit).splitlines():
            if not line.strip():
                continue
            meta, _, path = line.partition("\t")
            parts = meta.split()
            if len(parts) < 3 or parts[1] != "blob":
                continue
            sha = parts[2]
            blob_commits[sha].add(commit)
            blob_paths[sha].add(path)

    head = _git(mirror, "rev-parse", "HEAD").strip()
    head_blobs = set()
    for line in _git(mirror, "ls-tree", "-r", "--full-tree", head).splitlines():
        parts = line.partition("\t")[0].split()
        if len(parts) >= 3 and parts[1] == "blob":
            head_blobs.add(parts[2])

    # Cross-check against the object enumeration the brief names as the law.
    listed = set()
    for line in _git(mirror, "rev-list", "--objects", "--all").splitlines():
        sha, _, _name = line.partition(" ")
        listed.add(sha.strip())
    missing = set(blob_commits) - listed
    if missing:
        raise RuntimeError(
            "population mismatch: %d blobs reached by tree walk are absent "
            "from `rev-list --objects --all`" % len(missing)
        )
    return blob_paths, blob_commits, head_blobs, len(commits)


def read_blobs(mirror: str, shas):
    """Yield (sha, bytes) for each sha, one `git cat-file --batch` process.

    The request list is fed by a WRITER THREAD, deliberately. Writing the whole
    list inline deadlocks: `git cat-file --batch` starts emitting immediately,
    fills its stdout pipe (as little as 4 KB on Windows) and blocks, at which
    point it stops draining stdin, and a request list larger than the stdin
    pipe buffer blocks the writer forever. Nobody moves. This cost three
    silent multi-minute hangs before it was instrumented, so the thread stays
    and this comment stays with it.
    """
    shas = list(shas)
    if not shas:
        return
    proc = subprocess.Popen(
        ["git", "--git-dir", mirror, "cat-file", "--batch"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
    )

    def _feed():
        try:
            proc.stdin.write(("\n".join(shas) + "\n").encode("ascii"))
            proc.stdin.close()
        except (BrokenPipeError, OSError):
            pass

    writer = threading.Thread(target=_feed, daemon=True)
    writer.start()
    try:
        for sha in shas:
            header = proc.stdout.readline().decode("ascii", "replace").strip()
            parts = header.split()
            if len(parts) != 3 or parts[1] != "blob":
                raise RuntimeError("unexpected cat-file header: %r" % header)
            size = int(parts[2])
            # A pipe read can come back short. Loop, or a large blob is
            # silently truncated and the census under-reports.
            chunks, got = [], 0
            while got < size:
                chunk = proc.stdout.read(size - got)
                if not chunk:
                    raise RuntimeError(
                        "cat-file stream ended %d bytes into a %d byte blob "
                        "(%s) -- refusing to scan a truncated corpus"
                        % (got, size, sha)
                    )
                chunks.append(chunk)
                got += len(chunk)
            proc.stdout.read(1)  # trailing newline
            yield sha, b"".join(chunks)
    finally:
        proc.stdout.close()
        proc.wait()


def is_binary(data: bytes) -> bool:
    """Content sniff, never extension. A NUL in the leading window, or a
    high proportion of bytes outside the printable/whitespace range."""
    window = data[:BINARY_SNIFF_WINDOW]
    if not window:
        return False
    if b"\x00" in window:
        return True
    printable = sum(
        1 for b in window if 32 <= b < 127 or b in (9, 10, 13) or b >= 128
    )
    return (printable / len(window)) < 0.85


# --------------------------------------------------------------------------
# Detection
# --------------------------------------------------------------------------

Hit = collections.namedtuple("Hit", "shape value line_no context_kind")


def _line_is_hash_noise(path_hint: str, line: str) -> bool:
    name = path_hint.rsplit("/", 1)[-1].lower()
    if name.startswith("requirements") and name.endswith(".txt"):
        return True
    if name.endswith(".lock") or name in LOCK_NAMES:
        return True
    return bool(GIT_SHA40.search(line))


def detect(text: str, path_hint: str):
    """Yield Hit for every identity-shaped run in one blob's text."""
    # SIGN-OFF runs over the WHOLE text, not per line: the shape spans a line
    # break, and inside a JSON string that break is the two-character escape
    # \r\n on a single physical line. Both forms are matched.
    for m in SIGNOFF_LINE.finditer(text):
        line_no = text.count("\n", 0, m.start()) + 1
        yield Hit("SIGNOFF-NAME", m.group(1).strip(), line_no, "signoff")

    for line_no, line in enumerate(text.splitlines(), start=1):
        hash_noise = _line_is_hash_noise(path_hint, line)

        for m in EMAIL_SHAPE.finditer(line):
            if hash_noise:
                continue
            yield Hit("EMAIL", m.group(0), line_no, "")

        for m in MAILTO.finditer(line):
            yield Hit("EMAIL", m.group(1), line_no, "mailto")

        if not hash_noise:
            for name, pat in (("PHONE-IN", PHONE_IN_SHAPE),
                              ("PHONE-E164", PHONE_E164_SHAPE),
                              ("PHONE-NANP", PHONE_NANP_SHAPE)):
                for m in pat.finditer(line):
                    yield Hit(name, m.group(0), line_no, "")

        for m in LINKEDIN_SLUG.finditer(line):
            yield Hit("PROFILE-SLUG", m.group(1), line_no, "")

        for name, pat, grp in (("LI-COMPANY-ID", LINKEDIN_COMPANY_ID, 1),
                               ("LI-MEMBER-TOKEN", LINKEDIN_MEMBER_TOKEN, 0),
                               ("LI-URN-ID", LINKEDIN_URN_ID, 1)):
            for m in pat.finditer(line):
                yield Hit(name, m.group(grp), line_no, "")

        if not hash_noise:
            for m in JWT_SHAPE.finditer(line):
                yield Hit("CREDENTIAL-JWT", m.group(0), line_no, "")
            for m in COOKIE_ASSIGNMENT.finditer(line):
                yield Hit("CREDENTIAL-COOKIE", m.group(2), line_no, m.group(1))

        role = ROLE_WORD.search(line)
        if role:
            for m in TITLECASE_RUN.finditer(line):
                yield Hit("NAME-NEAR-ROLE", m.group(1), line_no,
                          role.group(1).lower())

        for m in AT_HANDLE.finditer(line):
            yield Hit("AT-HANDLE", m.group(1), line_no, "")

        for m in PERSON_URL.finditer(line):
            yield Hit("PERSON-URL", m.group(1), line_no, "")


def boundary_delta(text: str, path_hint: str):
    """Phone matches the DIGIT-boundary regex finds that the TOKEN-boundary
    regex does not. Measured so the stricter law cannot hide anything."""
    extra = set()
    for line in text.splitlines():
        if _line_is_hash_noise(path_hint, line):
            continue
        tok = {m.group(0) for m in PHONE_IN_SHAPE.finditer(line)}
        dig = {m.group(0) for m in PHONE_IN_DIGITBOUND.finditer(line)}
        extra |= (dig - tok)
    return extra


# --------------------------------------------------------------------------
# Classification
# --------------------------------------------------------------------------

CLASS_A = "A"        # third-party living person
CLASS_B = "B"        # the repo owner
CLASS_C = "C"        # synthetic
CLASS_AQ = "A?"      # cannot classify confidently


def owner_identity(mirror: str):
    """Owner identifiers DERIVED from history, never hardcoded.

    Commit author/committer name and email are already inside every clone,
    so deriving from them adds no new exposure. Returns lowercased sets.
    """
    emails, names, locals_ = set(), set(), set()
    out = _git(mirror, "log", "--all", "--format=%ae%n%ce%n%an%n%cn")
    for raw in out.splitlines():
        raw = raw.strip()
        if not raw:
            continue
        if "@" in raw:
            emails.add(raw.lower())
            locals_.add(raw.rsplit("@", 1)[0].lower())
        else:
            names.add(raw.lower())
    extra = os.environ.get("CENSUS_OWNER_TERMS", "")
    for term in extra.split(","):
        term = term.strip().lower()
        if term:
            names.add(term)
    return emails, names, locals_


def _name_tokens(text: str):
    return {t for t in re.split(r"[^a-z0-9]+", text.lower()) if len(t) >= 3}


def classify(shape: str, value: str, owner):
    """Return (class, reason-slug). Reason slugs never carry the value."""
    owner_emails, owner_names, owner_locals = owner
    low = value.lower()
    tokens = _name_tokens(value)
    owner_tokens = set()
    for n in owner_names:
        owner_tokens |= _name_tokens(n)
    for l in owner_locals:
        owner_tokens |= _name_tokens(l)
    owner_tokens = {t for t in owner_tokens if len(t) >= 4}

    if shape == "EMAIL":
        if _email_is_synthetic(value):
            return CLASS_C, "reserved-or-stub-domain"
        if low in owner_emails:
            return CLASS_B, "exact-owner-commit-address"
        if _has_synthetic_token(_email_local(value)):
            return CLASS_C, "synthetic-token-in-local-part"
        if tokens & owner_tokens:
            return CLASS_B, "owner-token-in-address"
        return CLASS_AQ, "real-shaped-address-unattributed"

    if shape == "SIGNOFF-NAME":
        if _has_synthetic_token(value):
            return CLASS_C, "synthetic-token-in-signoff"
        if tokens & owner_tokens:
            return CLASS_B, "owner-name-in-signoff"
        return CLASS_AQ, "given-name-in-signoff-position"

    if shape in ("PHONE-IN", "PHONE-E164", "PHONE-NANP"):
        if _phone_is_synthetic(value):
            return CLASS_C, "zeroed-classic-or-walk"
        return CLASS_AQ, "phone-shaped-run-unattributed"

    if shape == "PROFILE-SLUG":
        if _has_synthetic_token(value):
            return CLASS_C, "synthetic-token-in-slug"
        if tokens & owner_tokens:
            return CLASS_B, "owner-token-in-slug"
        return CLASS_AQ, "personal-slug-unattributed"

    if shape in ("LI-COMPANY-ID", "LI-URN-ID", "LI-MEMBER-TOKEN"):
        return CLASS_AQ, "opaque-id-see-sibling-census"

    if shape in ("CREDENTIAL-JWT", "CREDENTIAL-COOKIE"):
        if _credential_is_placeholder(value):
            return CLASS_C, "placeholder-marker"
        if tokens & owner_tokens:
            return CLASS_B, "owner-token-in-credential"
        return CLASS_AQ, "credential-shaped-unattributed"

    if shape == "NAME-NEAR-ROLE":
        if _has_synthetic_token(value):
            return CLASS_C, "synthetic-token-in-name"
        if tokens & owner_tokens:
            return CLASS_B, "owner-name-token"
        return CLASS_AQ, "titlecase-run-near-role-word"

    if shape == "AT-HANDLE":
        if _has_synthetic_token(value):
            return CLASS_C, "synthetic-token-in-handle"
        if tokens & owner_tokens:
            return CLASS_B, "owner-token-in-handle"
        return CLASS_AQ, "at-handle-unattributed"

    if shape == "PERSON-URL":
        tail = value.rsplit("/", 1)[-1].lstrip("@").lower()
        if _has_synthetic_token(tail):
            return CLASS_C, "synthetic-token-in-url"
        if tail in NON_PERSON_URL_TOKENS:
            return CLASS_C, "org-or-project-path-not-person"
        if _name_tokens(tail) & owner_tokens:
            return CLASS_B, "owner-token-in-url"
        return CLASS_AQ, "person-url-unattributed"

    return CLASS_AQ, "unrecognised-shape"


# --------------------------------------------------------------------------
# Scan drivers
# --------------------------------------------------------------------------


def scan_mirror(mirror: str):
    blob_paths, blob_commits, head_blobs, commit_count = enumerate_population(mirror)

    stats = {
        "commits": commit_count,
        "blobs_total": len(blob_commits),
        "blobs_binary": 0,
        "blobs_excluded_self": 0,
        "blobs_scanned": 0,
        "bytes_scanned": 0,
    }

    # (shape, value) -> record
    findings = {}
    boundary_extras = set()

    for sha, data in read_blobs(mirror, sorted(blob_commits)):
        paths = blob_paths[sha]
        if any(p.endswith(EXCLUDED_PATH_SUFFIXES) for p in paths):
            stats["blobs_excluded_self"] += 1
            continue
        if is_binary(data):
            stats["blobs_binary"] += 1
            continue
        stats["blobs_scanned"] += 1
        stats["bytes_scanned"] += len(data)
        text = data.decode("utf-8", "replace")
        path_hint = sorted(paths)[0]

        boundary_extras |= boundary_delta(text, path_hint)

        for hit in detect(text, path_hint):
            key = (hit.shape, hit.value)
            rec = findings.get(key)
            if rec is None:
                rec = {
                    "shape": hit.shape,
                    "value": hit.value,
                    "handle": _sha(hit.value),
                    "paths": set(),
                    "commits": set(),
                    "blobs": set(),
                    "live_at_head": False,
                    "contexts": set(),
                    "occurrences": 0,
                }
                findings[key] = rec
            rec["paths"] |= paths
            rec["commits"] |= blob_commits[sha]
            rec["blobs"].add(sha)
            rec["occurrences"] += 1
            if hit.context_kind:
                rec["contexts"].add(hit.context_kind)
            if sha in head_blobs:
                rec["live_at_head"] = True

    return findings, stats, boundary_extras


def scan_dir(root: str):
    """Control mode: scan plain files on disk, same detectors."""
    findings = {}
    for dirpath, _dirs, files in os.walk(root):
        for name in sorted(files):
            full = os.path.join(dirpath, name)
            rel = os.path.relpath(full, root).replace("\\", "/")
            with open(full, "rb") as fh:
                data = fh.read()
            if is_binary(data):
                continue
            text = data.decode("utf-8", "replace")
            for hit in detect(text, rel):
                key = (hit.shape, hit.value)
                rec = findings.setdefault(key, {
                    "shape": hit.shape, "value": hit.value,
                    "handle": _sha(hit.value), "paths": set(),
                    "commits": set(), "blobs": set(), "live_at_head": False,
                    "contexts": set(), "occurrences": 0,
                })
                rec["paths"].add(rel)
                rec["occurrences"] += 1
    return findings


# --------------------------------------------------------------------------
# Reporting -- handles only, never values
# --------------------------------------------------------------------------

ALL_SHAPES = (
    "EMAIL", "PHONE-IN", "PHONE-E164", "PHONE-NANP", "PROFILE-SLUG",
    "SIGNOFF-NAME",
    "LI-COMPANY-ID", "LI-MEMBER-TOKEN", "LI-URN-ID",
    "CREDENTIAL-JWT", "CREDENTIAL-COOKIE",
    "NAME-NEAR-ROLE", "AT-HANDLE", "PERSON-URL",
)


def build_rows(findings, owner, overrides=None):
    overrides = overrides or {}
    rows = []
    counters = collections.Counter()
    for (shape, value), rec in findings.items():
        cls, reason = classify(shape, value, owner)
        handle = rec["handle"]
        if handle in overrides:
            cls, reason = overrides[handle]
        counters[cls] += 1
        rows.append({
            "class": cls,
            "reason": reason,
            "shape": shape,
            "handle": handle,
            "paths": sorted(rec["paths"]),
            "n_paths": len(rec["paths"]),
            "commits": len(rec["commits"]),
            "blobs": len(rec["blobs"]),
            "live_at_head": rec["live_at_head"],
            "occurrences": rec["occurrences"],
            "contexts": sorted(rec["contexts"]),
        })
    order = {CLASS_A: 0, CLASS_AQ: 1, CLASS_B: 2, CLASS_C: 3}
    rows.sort(key=lambda r: (order.get(r["class"], 9), r["shape"],
                             -r["commits"], r["handle"]))
    label_seq = collections.Counter()
    for row in rows:
        label_seq[row["class"]] += 1
        row["label"] = "%s%d" % (row["class"].rstrip("?"), label_seq[row["class"]])
        if row["class"] == CLASS_AQ:
            row["label"] = "AQ%d" % label_seq[row["class"]]
    return rows, counters


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mirror")
    ap.add_argument("--control")
    ap.add_argument("--out")
    ap.add_argument("--triage", action="store_true")
    ap.add_argument("--json")
    ap.add_argument("--overrides", help="JSON: handle -> [class, reason]")
    args = ap.parse_args()

    if args.control:
        findings = scan_dir(args.control)
        by_shape = collections.Counter(s for (s, _v) in findings)
        print("CONTROL SCAN of %s" % args.control)
        for shape in ALL_SHAPES:
            print("  %-18s %s" % (shape, by_shape.get(shape, 0)))
        print("distinct hits: %d" % len(findings))
        return 0

    if not args.mirror:
        ap.error("--mirror is required unless --control is given")

    owner = owner_identity(args.mirror)
    findings, stats, extras = scan_mirror(args.mirror)

    overrides = {}
    if args.overrides and os.path.exists(args.overrides):
        with open(args.overrides, "r", encoding="ascii") as fh:
            overrides = {k: tuple(v) for k, v in json.load(fh).items()}

    rows, counters = build_rows(findings, owner, overrides)

    if args.triage:
        # STDOUT ONLY, for a human classifying the residual. Never the report.
        for (shape, value), rec in sorted(findings.items()):
            cls, reason = classify(shape, value, owner)
            if cls != CLASS_AQ:
                continue
            print("%-18s %s  n_commits=%d head=%s  %s\n    VALUE: %r\n    PATHS: %s"
                  % (shape, rec["handle"], len(rec["commits"]),
                     rec["live_at_head"], reason, value,
                     ", ".join(sorted(rec["paths"])[:6])))
        return 0

    if args.json:
        with open(args.json, "w", encoding="ascii") as fh:
            json.dump({"stats": stats, "rows": rows,
                       "boundary_delta": len(extras),
                       "counters": dict(counters)}, fh, indent=1)

    zero_shapes = [s for s in ALL_SHAPES
                   if not any(r["shape"] == s for r in rows)]
    print(json.dumps({
        "stats": stats,
        "counters": dict(counters),
        "distinct_findings": len(rows),
        "zero_shapes": zero_shapes,
        "boundary_delta": len(extras),
    }, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
