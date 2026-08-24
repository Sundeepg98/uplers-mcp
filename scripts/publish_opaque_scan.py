"""Hunt opaque, account-scoped handles ahead of a make-public.

The shape-based identity scanners (names, emails, phones, LinkedIn slugs) are a
DIFFERENT instrument and this one deliberately does not duplicate them. This one
owns the residue: values with NO recognisable personal shape - a 32-character
alphanumeric blob, a seven-digit integer, a Gmail thread handle - which a human
reading the diff files under "opaque hash, probably a checksum" and walks past.
That is exactly how a live `profileId` survived a certified scrub in a sibling
repo the day before this was written.

THE OUTPUT CONTRACT, which is not negotiable: this program never emits a value.
Every value it has ever seen leaves as `sha256(value)[:8]`, called a HANDLE. A
handle distinguishes two values and links the same value across two keys, which
is all a reader needs; the value itself in a report is a fresh copy of the
problem the report exists to close.

Authority is the MIRROR of the published remote, walked over `rev-list --all`,
because HEAD is not history: a value deleted in the working tree is still served
by the remote forever. Every finding is stamped HEAD or HISTORY-ONLY.

Entropy is used as a FILTER and never as a decider. A 32-character hex string is
a git sha, a content digest or an account handle, and only the KEY and the
CONTAINING PATH separate those three. Each admitted row therefore records which
test admitted it.

Usage:
    python scripts/publish_opaque_scan.py --mirror <bare-repo>
    python scripts/publish_opaque_scan.py --control
"""

from __future__ import annotations

import argparse
import collections
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile

from urllib.parse import urlparse, parse_qs


# --------------------------------------------------------------------------
# handles
# --------------------------------------------------------------------------

def handle(value):
    """The only channel a value is ever allowed to leave this program through."""
    return hashlib.sha256(str(value).encode("utf-8", "replace")).hexdigest()[:8]


def entropy(s):
    if not s:
        return 0.0
    counts = collections.Counter(s)
    n = float(len(s))
    return -sum((c / n) * math.log(c / n, 2) for c in counts.values())


# --------------------------------------------------------------------------
# shape classification
# --------------------------------------------------------------------------

_UUID = re.compile(r"\A[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
                   r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\Z")
_JWT = re.compile(r"\Aey[A-Za-z0-9_-]{6,}\.[A-Za-z0-9_-]{4,}\.[A-Za-z0-9_-]{4,}\Z")


def shape_of(value):
    """A name for the value's FORM. Never returns any part of the value."""
    s = str(value)
    n = len(s)
    if _JWT.match(s):
        return "jwt(%d)" % n
    if _UUID.match(s):
        return "uuid(36)"
    if re.fullmatch(r"[0-9]+", s):
        return "digits(%d)" % n
    if re.fullmatch(r"[0-9a-f]+", s):
        return "lowerhex(%d)" % n
    if re.fullmatch(r"[0-9A-F]+", s):
        return "upperhex(%d)" % n
    if re.fullmatch(r"[0-9a-zA-Z]+", s):
        return "alnum(%d)" % n
    if re.fullmatch(r"[0-9a-zA-Z_-]+", s):
        return "alnum_dash(%d)" % n
    if re.fullmatch(r"[0-9a-zA-Z+/=_-]+", s):
        return "base64ish(%d)" % n
    if s.startswith("http://") or s.startswith("https://"):
        return "url(%d)" % n
    return "other(%d)" % n


# --------------------------------------------------------------------------
# key classification
#
# Two lists on purpose. ACCOUNT_KEY is the set whose NAME alone says "this
# addresses somebody" - it admits a value regardless of how boring the value
# looks. GENERIC_ID_KEY is the enormous grey set (`id`, `type`, `order`) where
# the name says nothing and the VALUE has to earn admission on its own.
# --------------------------------------------------------------------------

ACCOUNT_KEY = re.compile(
    r"(?:^|_)(?:"
    r"enc_?id|talent_?id|profile_?id|user_?id|candidate_?id|account_?id|"
    r"member_?id|person_?id|people_?id|employee_?id|employer_?id|"
    r"recruiter_?id|hr_?id|poc_?id|contact_?id|client_?id|customer_?id|"
    r"ta_?id|matcher_?id|owner_?id|creator_?id|author_?id|"
    r"thread_?id|message_?id|conversation_?id|mail_?id|email_?id|"
    r"audience_?id|campaign_?id|subscriber_?id|lead_?id|"
    r"session|sessionid|cookie|csrf|xsrf|token|bearer|authorization|auth|"
    r"secret|password|passwd|credential|api_?key|access_?key|private_?key|"
    r"signature|master_?key|sub|uid|guid|uuid"
    r")$",
    re.IGNORECASE,
)

# Keys whose name is a bare noun and carries no ownership claim at all.
GENERIC_ID_KEY = re.compile(r"(?:^|_)(?:id|ids|key|no|number|ref|slug|code)$",
                            re.IGNORECASE)

# `_by` columns are an audit trail: the value is a USER of the platform, which
# on a staff-operated board means a THIRD PARTY. Named separately because no
# published id-key list contains them and they are trivially missed.
ACTOR_KEY = re.compile(r"_by$", re.IGNORECASE)

# A credential is not an identifier: holding it ACTS, it does not merely name.
SIGNED_URL_PARAM = re.compile(
    r"[?&](?:X-Amz-Signature|X-Amz-Credential|X-Amz-Security-Token|"
    r"X-Goog-Signature|AWSAccessKeyId|GoogleAccessId|Signature|sig|se|st|sp|sv)=",
    re.IGNORECASE,
)
BEARERISH = re.compile(r"\A(?:Bearer|Basic|Token)\s+\S{8,}\Z", re.IGNORECASE)


# --------------------------------------------------------------------------
# The two discriminators entropy cannot supply.
#
# 1. WORDS AND IDENTIFIERS. `strong_proficiencyskills` is 24 characters with a
#    Shannon entropy of 3.7, which is indistinguishable from a real handle by
#    any entropy threshold. It is a VARIABLE NAME. Running the value-only rule
#    over source text without this filter produced ~5,900 rows of Python
#    identifiers, which is the exact failure the brief predicted: entropy is a
#    filter, never a decider.
# 2. GIT OBJECT IDS. A 40-character lowercase hex string in a repo is almost
#    always a commit this repo already publishes. That is decidable, not
#    guessable: ask the object database whether the id resolves.
# --------------------------------------------------------------------------

_WORD = re.compile(r"\A[A-Za-z]+\Z")
_SNAKE = re.compile(r"\A[A-Za-z][A-Za-z0-9]*(?:_[A-Za-z0-9]+)+\Z")
_KEBAB = re.compile(r"\A[A-Za-z]+(?:-[A-Za-z]+)+\Z")
_CAMEL = re.compile(r"\A(?:[A-Z][a-z]+){2,}\Z")
_DOTTED = re.compile(r"\A[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)+\Z")


def looks_like_identifier(s):
    """True when the token is a name a programmer typed, not a value."""
    if _WORD.match(s) or _KEBAB.match(s) or _CAMEL.match(s) or _DOTTED.match(s):
        return True
    if _SNAKE.match(s):
        segs = s.split("_")
        alpha = sum(1 for g in segs if re.fullmatch(r"[A-Za-z]+", g))
        return alpha >= max(2, len(segs) - 1)
    return False


def opaque_density(s):
    """Fraction of the token that is digits. A handle is dense; a name is not."""
    d = sum(1 for c in s if c.isdigit())
    return d / float(len(s)) if s else 0.0


class GitObjectOracle(object):
    """Answers 'is this hex string a commit/tree/blob this repo already has?'"""

    def __init__(self, repo):
        self.repo = repo
        self.cache = {}

    def resolves(self, s):
        if not re.fullmatch(r"[0-9a-f]{7,40}", s):
            return False
        if s in self.cache:
            return self.cache[s]
        r = subprocess.run(["git", "-C", self.repo, "cat-file", "-t", s],
                           capture_output=True, text=True)
        ok = r.returncode == 0
        self.cache[s] = ok
        return ok


# --------------------------------------------------------------------------
# admission
# --------------------------------------------------------------------------

TIER_CRED = "CRED"        # holding it acts: jwt, bearer, presigned signature
TIER_OPAQUE = "OPAQUE"    # a long high-entropy handle, whatever the key says
TIER_ACCOUNT = "ACCT"     # a boring value under a key that names a person
TIER_TRIVIAL = "TRIVIAL"  # enumerable small integer; recorded, not alarmed on


#: Query parameters that name an ACCOUNT rather than a resource. Short and
#: lowercase, so they never look like identifiers to the key regex above.
URL_ACCOUNT_PARAM = frozenset((
    "ouid", "authuser", "uid", "userid", "user_id", "gid", "account",
    "accountid", "member", "memberid", "profileid", "talentid", "sub",
))

#: Parameters that mean "this link stops working at time T". An expiry beside an
#: opaque token is the definition of a signed URL, whatever the token is called.
URL_EXPIRY_PARAM = frozenset((
    "e", "exp", "expires", "expiry", "se", "x-amz-expires", "x-goog-expires",
))


def _admit_url_query(url):
    try:
        q = parse_qs(urlparse(url).query, keep_blank_values=False)
    except ValueError:
        return None, None
    if not q:
        return None, None
    has_expiry = any(p.lower() in URL_EXPIRY_PARAM for p in q)
    for p, vals in q.items():
        pl = p.lower()
        for qv in vals:
            if (pl in URL_ACCOUNT_PARAM or ACCOUNT_KEY.search(p)) and len(qv) >= 6:
                return TIER_ACCOUNT, "account handle in URL query param '%s'" % pl
            if (has_expiry and pl not in URL_EXPIRY_PARAM
                    and re.fullmatch(r"[A-Za-z0-9_-]{20,}", qv)):
                return TIER_CRED, ("URL carries an expiry plus an opaque token "
                                   "in param '%s' (signed URL)" % pl)
    return None, None


def admit(key, value):
    """Return (tier, test_name) or (None, reason). The TEST is reported."""
    if value is True or value is False:
        return None, "boolean"
    s = str(value)
    if not s:
        return None, "empty"

    if _JWT.match(s):
        return TIER_CRED, "jwt-triple-segment"
    if BEARERISH.match(s):
        return TIER_CRED, "bearer-scheme-prefix"
    if s.startswith("http") and SIGNED_URL_PARAM.search(s):
        return TIER_CRED, "presigned-url-signature-param"

    # A URL is a container, not a scalar. Both shapes this scanner originally
    # walked past were hiding INSIDE one: a LinkedIn CDN logo signed with `t=`
    # (a signature parameter nobody's list calls "signature"), and a Google Docs
    # JD link carrying `ouid=` (a third party's Google account handle, under no
    # key at all). Rather than lengthen the parameter list - which is the same
    # enumeration trap one level down - parse the query string and run THIS SAME
    # admission over every parameter it contains.
    if s.startswith("http"):
        tier, test = _admit_url_query(s)
        if tier:
            return tier, test

    key = key or ""
    key_is_account = bool(ACCOUNT_KEY.search(key))
    key_is_actor = bool(ACTOR_KEY.search(key))

    # OPAQUE: long enough that it cannot be guessed, mixed enough that it is not
    # a counter or a date. Admitted on VALUE alone - this is the rule that needs
    # no key list, and therefore the rule that survives an API adding a key
    # nobody has enumerated yet.
    if re.fullmatch(r"[0-9a-zA-Z_-]+", s) and len(s) >= 16 and entropy(s) >= 3.0:
        if not re.fullmatch(r"[0-9]+", s):
            return TIER_OPAQUE, "len>=16 + alnum charset + shannon>=3.0"

    # ACCOUNT: the key names a person or a conversation, so even a dull value is
    # a handle. Guarded against the flag-as-id case (0/1 under `self_applied_by`)
    # and against enumerable 1-3 digit lookup codes.
    if key_is_account or key_is_actor:
        if re.fullmatch(r"[0-9]+", s):
            if len(s) <= 3:
                return TIER_TRIVIAL, "account-key but <=3 digits (enumerable code)"
            return TIER_ACCOUNT, "account-key + >=4 digits"
        if len(s) >= 8:
            return TIER_ACCOUNT, "account-key + >=8 char non-numeric"
        return TIER_TRIVIAL, "account-key but short non-numeric"

    if GENERIC_ID_KEY.search(key) and re.fullmatch(r"[0-9]+", s):
        return TIER_TRIVIAL, "generic id-key + pure digits (no ownership claim)"

    return None, "no test matched"


# --------------------------------------------------------------------------
# walking
# --------------------------------------------------------------------------

class Row(object):
    __slots__ = ("locus", "key", "shape", "tier", "test", "h", "blobpath", "in_head")

    def __init__(self, locus, key, shape, tier, test, h, blobpath, in_head):
        self.locus = locus
        self.key = key
        self.shape = shape
        self.tier = tier
        self.test = test
        self.h = h
        self.blobpath = blobpath
        self.in_head = in_head


def norm_path(jp):
    return re.sub(r"\[\d+\]", "[i]", jp)


def walk_json(obj, blobpath, in_head, out, jp="$"):
    if isinstance(obj, dict):
        for k, v in obj.items():
            walk_json(v, blobpath, in_head, out, jp + "." + str(k))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            walk_json(v, blobpath, in_head, out, jp + "[%d]" % i)
    elif obj is None:
        return
    else:
        key = jp.rsplit(".", 1)[-1]
        key = re.sub(r"\[\d+\]$", "", key)
        tier, test = admit(key, obj)
        if tier:
            out.append(Row(norm_path(jp), key, shape_of(obj), tier, test,
                           handle(obj), blobpath, in_head))


ASSIGN = re.compile(
    r"(?P<key>[A-Za-z_][A-Za-z0-9_.-]{1,60})"
    r"[\"']?\s*[:=]\s*[\"']?(?P<val>[A-Za-z0-9_.:/+=-]{4,600})")
FREE_TOKEN = re.compile(r"(?<![A-Za-z0-9_])(?P<val>[A-Za-z0-9_-]{16,200})(?![A-Za-z0-9_])")
URL_TOKEN = re.compile(r"(?<![A-Za-z0-9_])(?P<val>https?://[^\s\"'<>)\]]{8,900})")


def walk_text(text, blobpath, in_head, out, oracle=None):
    seen = set()
    for m in URL_TOKEN.finditer(text):
        v = m.group("val")
        tier, test = admit("url", v)
        if tier and (v, "url") not in seen:
            seen.add((v, "url"))
            out.append(Row(blobpath, "<url-literal>", shape_of(v), tier, test,
                           handle(v), blobpath, in_head))
    for m in ASSIGN.finditer(text):
        k, v = m.group("key"), m.group("val")
        if looks_like_identifier(v):
            continue
        tier, test = admit(k, v)
        if tier and tier != TIER_TRIVIAL and (v, k) not in seen:
            seen.add((v, k))
            out.append(Row(blobpath, k, shape_of(v), tier, test, handle(v),
                           blobpath, in_head))
    for m in FREE_TOKEN.finditer(text):
        v = m.group("val")
        if (v, "") in seen:
            continue
        # Order matters: cheapest and most decisive rejections first.
        if looks_like_identifier(v):
            continue
        if oracle is not None and oracle.resolves(v):
            continue  # a git object id this repo already publishes
        if opaque_density(v) < 0.15 and not re.fullmatch(r"[0-9a-f]{32,}", v):
            continue  # too few digits to be a handle; it is prose or a name
        tier, test = admit("", v)
        if tier:
            seen.add((v, ""))
            out.append(Row(blobpath, "<bare-literal>", shape_of(v), tier,
                           test + " + not-identifier + digit-density>=0.15",
                           handle(v), blobpath, in_head))


# --------------------------------------------------------------------------
# git plumbing
# --------------------------------------------------------------------------

def git(repo, *args):
    return subprocess.run(["git", "-C", repo] + list(args),
                          capture_output=True, text=True, errors="replace").stdout


def enumerate_blobs(repo):
    """(sha, path) for every blob reachable from every ref, ever."""
    out = git(repo, "rev-list", "--objects", "--all")
    pairs = []
    for line in out.splitlines():
        parts = line.split(" ", 1)
        if len(parts) == 2 and parts[1].strip():
            pairs.append((parts[0], parts[1].strip()))
    return pairs


def head_blob_shas(repo):
    shas = set()
    for line in git(repo, "ls-tree", "-r", "HEAD").splitlines():
        f = line.split()
        if len(f) >= 3 and f[1] == "blob":
            shas.add(f[2])
    return shas


def read_blobs(repo, shas):
    """Stream blob bodies over one `cat-file --batch` process."""
    p = subprocess.Popen(["git", "-C", repo, "cat-file", "--batch"],
                         stdin=subprocess.PIPE, stdout=subprocess.PIPE)
    try:
        for sha in shas:
            p.stdin.write((sha + "\n").encode())
            p.stdin.flush()
            header = p.stdout.readline().decode("utf-8", "replace").split()
            if len(header) < 3:
                yield sha, None
                continue
            size = int(header[2])
            buf = b""
            while len(buf) < size:
                chunk = p.stdout.read(size - len(buf))
                if not chunk:
                    break
                buf += chunk
            p.stdout.read(1)
            yield sha, buf
    finally:
        try:
            p.stdin.close()
        except Exception:
            pass
        p.wait()


SELF_EXCLUDE = ("scripts/publish_opaque_scan.py",
                "_audit/_slices/_slice-publish-opaque-tokens.md")


def scan_repo(repo):
    pairs = enumerate_blobs(repo)
    head = head_blob_shas(repo)
    rows = []
    skipped_self = 0
    binary = 0
    oracle = GitObjectOracle(repo)
    by_sha = collections.OrderedDict()
    for sha, path in pairs:
        by_sha.setdefault(sha, []).append(path)
    order = list(by_sha.keys())
    for sha, body in read_blobs(repo, order):
        paths = by_sha.get(sha, [])
        if any(p in SELF_EXCLUDE for p in paths):
            skipped_self += 1
            continue
        if body is None or b"\x00" in body[:8192]:
            binary += 1
            continue
        try:
            text = body.decode("utf-8")
        except UnicodeDecodeError:
            binary += 1
            continue
        in_head = sha in head
        display = paths[0]
        if display.endswith(".json"):
            try:
                walk_json(json.loads(text), display, in_head, rows)
                continue
            except (ValueError, RecursionError):
                pass
        walk_text(text, display, in_head, rows, oracle)
    return rows, {"blobs": len(by_sha), "pairs": len(pairs),
                  "head_blobs": len(head), "binary": binary,
                  "skipped_self": skipped_self}


# --------------------------------------------------------------------------
# aggregation
# --------------------------------------------------------------------------

def aggregate(rows):
    agg = collections.OrderedDict()
    for r in rows:
        k = (r.tier, r.locus, r.key, r.shape)
        e = agg.setdefault(k, {"occ": 0, "handles": set(), "test": r.test,
                               "head": False, "hist": False, "files": set()})
        e["occ"] += 1
        e["handles"].add(r.h)
        e["files"].add(r.blobpath)
        if r.in_head:
            e["head"] = True
        else:
            e["hist"] = True
    return agg


def render(agg, stats, stream=sys.stdout, tiers=None):
    order = {TIER_CRED: 0, TIER_OPAQUE: 1, TIER_ACCOUNT: 2, TIER_TRIVIAL: 3}
    items = sorted(agg.items(), key=lambda kv: (order.get(kv[0][0], 9),
                                                -len(kv[1]["handles"]), kv[0][1]))
    stream.write("blobs=%(blobs)d pairs=%(pairs)d head_blobs=%(head_blobs)d "
                 "binary_skipped=%(binary)d self_skipped=%(skipped_self)d\n\n"
                 % stats)
    stream.write("%-7s %-58s %-24s %-16s %5s %5s %-12s %s\n" %
                 ("TIER", "LOCUS", "KEY", "SHAPE", "OCC", "DIST", "WHERE", "TEST"))
    for (tier, locus, key, shape), e in items:
        if tiers and tier not in tiers:
            continue
        where = "HEAD" if e["head"] and not e["hist"] else (
            "HISTORY-ONLY" if e["hist"] and not e["head"] else "HEAD+HIST")
        stream.write("%-7s %-58s %-24s %-16s %5d %5d %-12s %s\n" %
                     (tier, locus[:58], key[:24], shape, e["occ"],
                      len(e["handles"]), where, e["test"]))


# --------------------------------------------------------------------------
# CONTROL: plant one synthetic token of every shape claimed, prove detection,
# remove. A check that has never been shown failing certifies nothing.
# --------------------------------------------------------------------------

CONTROL_SPECIMENS = [
    ("opaque-alnum32", "enc_id", "Qa7Zm3Kd9Lp2Rt5Wx8Yb1Nc4Vf6Hj0S"),
    ("opaque-lowerhex32", "digest_ref", "3f9a1c7e2b8d406f5a1e9c3b7d2f8a04"),
    ("uuid36", "resource_uuid", "6f1c2a4e-8b3d-4f27-9a05-1e7c3b9d2f84"),
    ("gmail-threadish17", "gmail_thread_id", "Kq7Zm3Xd9Lp2Rt5Wx"),
    ("account-digits7", "talent_id", "4820917"),
    ("thirdparty-digits6", "outreach_employee_id", "731905"),
    ("actor-digits7", "created_by", "5106284"),
    ("jwt", "session_token",
     "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJDT05UUk9MIn0.c0nTr0LsIgc0nTr0L"),
    ("bearer-header", "authorization", "Bearer Ab3Kd9Lp2Rt5Wx8Yb1Nc4Vf6Hj0Sq7Zm"),
    ("presigned-url", "resumePath_url",
     "https://ctrl.example.invalid/f.pdf?X-Amz-Signature=9a1c7e2b8d406f5a1e9c3b"),
    ("unnamed-key-opaque", "zzz_field_nobody_enumerated",
     "Wx8Yb1Nc4Vf6Hj0Sq7Zm3Kd9Lp2Rt5"),
    # Added after the first mirror pass FOUND both of these in the repo and the
    # scanner had walked past them. They are kept as specimens precisely because
    # they once failed: the first is a signed URL whose signature parameter is
    # not called "signature", the second is an account handle that never appears
    # as a key at all - it hides in a query string inside an ordinary link.
    ("signed-url-unlisted-param", "company_logo",
     "https://ctrl.example.invalid/logo.png?e=1789977600&v=beta&t=Ab3Kd9Lp2Rt5Wx8Yb1Nc4Vf6Hj0Sq7Zm3Kd9Lp2Rt"),
    ("account-handle-in-query-param", "jd_path",
     "https://ctrl.example.invalid/document/d/1Ab3Kd9Lp2Rt5Wx8Yb/edit?ouid=104729318264150937284&usp=sharing"),
]


def run_control():
    """Build a throwaway git repo, commit the specimens, scan it, tear it down."""
    tmp = tempfile.mkdtemp(prefix="opaque_control_")
    detected, missed = [], []
    try:
        subprocess.run(["git", "init", "-q", tmp], capture_output=True)
        subprocess.run(["git", "-C", tmp, "config", "user.email", "c@c.invalid"],
                       capture_output=True)
        subprocess.run(["git", "-C", tmp, "config", "user.name", "control"],
                       capture_output=True)
        payload = {"data": {"rows": [dict((k, v) for _, k, v in CONTROL_SPECIMENS)]}}
        with open(os.path.join(tmp, "fixture.json"), "w") as fh:
            json.dump(payload, fh)
        with open(os.path.join(tmp, "source.py"), "w") as fh:
            for _, k, v in CONTROL_SPECIMENS:
                fh.write('%s = "%s"\n' % (k, v))
        subprocess.run(["git", "-C", tmp, "add", "-A"], capture_output=True)
        subprocess.run(["git", "-C", tmp, "commit", "-q", "-m", "control"],
                       capture_output=True)
        rows, _ = scan_repo(tmp)
        found = set(r.h for r in rows)
        for name, _, v in CONTROL_SPECIMENS:
            if handle(v) in found:
                detected.append(name)
            else:
                missed.append(name)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return detected, missed


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mirror")
    ap.add_argument("--control", action="store_true")
    ap.add_argument("--tier", action="append")
    a = ap.parse_args()
    if a.control:
        det, miss = run_control()
        print("CONTROL detected (%d): %s" % (len(det), ", ".join(det)))
        print("CONTROL NOT detected (%d): %s" % (len(miss), ", ".join(miss) or "-"))
        return 0 if not miss else 2
    if not a.mirror:
        ap.error("--mirror or --control required")
    rows, stats = scan_repo(a.mirror)
    render(aggregate(rows), stats, tiers=set(a.tier) if a.tier else None)
    return 0


if __name__ == "__main__":
    sys.exit(main())
