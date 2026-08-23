"""Replace the resume recruiters see, and the pre-flight snapshot that is the only way back.

This is the second write in this server that changes WHO HE IS rather than
acting on a requisition, and it is the more dangerous of the two. Its sibling
:mod:`uplers_server.profile_write` can delete a list of skills; this one can
make a document unreachable. Uplers keeps no previous copy of it.

**The write is ONE multipart call.** VERIFIED in Uplers' own production bundle
at the profile page's own handler, `196.6de42d0ddab10b51.js` @104539::

    var e,t,n=new FormData;
    n.append("field","resume"),
    n.append("value",N),            // N is the raw File, never an id
    m&&n.append("tid",m),
    (0,c.P7)(n)(A)

which is::

    POST talent/profile-upsert      multipart/form-data
         field=resume
         value=<the file bytes>

The literals are LOWERCASE - a grep of all 86 bundle files returns zero hits
for an uppercase `RESUME_FILE_ID`. `tid` is an impersonation parameter read off
the URL query string (`A.get("tid")`) by staff viewing somebody else's profile;
acting as himself it is absent, so this module never builds it and
:func:`multipart_parts` cannot be talked into one. Full evidence, including the
other four call sites and the three-call presigned-PUT path this deliberately
does NOT build: `_audit/_slices/_slice-resume-write-shape.md`.

**THERE IS NO SERVER-SIDE REVERT, and that is the whole design constraint.**
VERIFIED absences across the whole corpus: `resume_history` 0 hits,
`resume_versions` 0, `previous_resume` 0, `old_resume` 0, `resume_archive` 0.
`talent/profile/delete-details` exists but is only ever called with six section
names and never with a resume. `resume_file_id` appears 8 times and all 8 are
WRITES - it is a one-shot upload token the client is never handed back, so
"read the old pointer, keep it, write it back later" does not exist.

What DOES exist is a read of the current file as real bytes::

    GET talent/talent-download-resume-profile?talent_id=<talent_enc_id>
      -> {blob: "<base64>", ext: "pdf"|"docx", filename: "<name>"}

It takes ONE parameter and no version, so it always returns THE CURRENT resume.
That is precisely what a pre-flight snapshot needs and precisely why a post-hoc
recovery is impossible: after the replacement the same route returns the new
file. **Miss the snapshot and the old document is unreachable forever.** Every
guard here exists to make missing it impossible.

**The snapshot restores the FILE, not the RECORD.** The undo is a fresh upload,
so server-side identity is new, and whether Uplers re-parses the resume,
re-scores him, notifies a recruiter, or touches an already-submitted
application is UNRESOLVED - see :data:`BLAST_RADIUS_UNRESOLVED`, which every
preview prints verbatim rather than summarising.

**A snapshot here is his actual resume sitting on this disk.** Its sibling
`profile_write.write_snapshot` deliberately stores skill rows and nothing else,
on the grounds that personal data on disk is a liability that buys nothing.
Here it buys the only rollback that exists, so the trade goes the other way -
but it is a trade, and it is stated rather than hidden. `data/` is gitignored.

**Nothing here can SEND THE WRITE.** `profile_write` states this as "nothing
here performs a request", and the property it is protecting is that the write
cannot fire as a side effect of anything. This module needs two READS to build
its snapshot, so it takes the same property one level in instead of dropping
it: the orchestrators below read, and they are HANDED a `send` callable. With
no sender they refuse. The upsert route constant is not named anywhere in this
file - `server.py` supplies it, which is what keeps
`test_the_upsert_route_is_reachable_from_the_write_tools_and_nowhere_else`
meaningful.

The orchestrators live here rather than in `server.py` for one reason: a test
that exercises a COPY of the tool proves nothing about the tool. The guards
below are the ones that run in production, and `server.py`'s wrappers are three
lines each.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import config, endpoints, policy

# The same guard class as the skills write, not a second one. A caller that
# catches WriteRefused must catch both profile writes, and two classes meaning
# "stopped before anything left the machine" is one class too many.
from .profile_write import WriteRefused

#: GET, one parameter, no version. Kept here rather than in `endpoints.py`
#: because this wave owns two new files and edits none - it belongs beside its
#: siblings and moving it there is a one-line follow-up.
#:
#: VERIFIED, `app.js`: ``(0,i.Yr)(o.f5v+"?talent_id="+e)`` where `f5v` is
#: ``talent/talent-download-resume-profile`` and `e` is the caller's own
#: `talent_enc_id` off the auth user.
EP_DOWNLOAD_RESUME = "talent/talent-download-resume-profile"

#: The multipart part names, spelled once. VERIFIED lowercase at all five
#: resume call sites in the bundle.
PART_FIELD = "field"
PART_VALUE = "value"
FIELD_RESUME = "resume"

#: Parts this module must NEVER build, and why each one is refused rather than
#: merely omitted:
#:
#: * `tid` - impersonation. Sending it aims the write at somebody else.
#: * `transformation_file_id` - only the Resume Health Check nudge sends it,
#:   and it is what flips Uplers' `is_resume_updated` flag. The profile-page
#:   path does not touch that state and neither does this.
#: * `resume_file_id` - the OTHER write path entirely (presigned PUT to
#:   third-party object storage). Mixing the two shapes is how a one-call write
#:   turns into a three-call one against a storage endpoint nobody audited.
NEVER_SENT = ("tid", "transformation_file_id", "resume_file_id")

#: VERIFIED from the `accept` attribute (`.docx,.pdf`) and the extension regex
#: at all five sites. Uplers' own 422 text is quoted in the refusal below.
ALLOWED_EXTENSIONS = ("pdf", "docx")

#: VERIFIED: the bundle rejects on ``n.size/1024>2048``, so a file is accepted
#: while `size/1024 <= 2048`, i.e. up to and including 2097152 bytes. Mirrored
#: to the byte rather than rounded, because a client guard stricter than the
#: server's refuses uploads the platform would have taken, and a looser one
#: turns a legible local refusal into a remote 422.
MAX_UPLOAD_BYTES = 2 * 1024 * 1024

#: What a browser puts on the file part. VERIFIED from the download decoder's
#: own mime strings, which is the same pair in the other direction.
CONTENT_TYPES = {
    "pdf": "application/pdf",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}

#: Same shape as `profile_write.SNAPSHOT_ID_RE`, and same reason: a restore is
#: far too destructive to run against a file of unknown origin, so an id this
#: server did not write is refused before anything on disk is touched.
SNAPSHOT_ID_RE = re.compile(r"[0-9]{1,20}-[a-z0-9-]{1,40}")

#: A filename travels into a multipart Content-Disposition header. These are
#: the characters that would end that header early or start a new one.
_UNSAFE_IN_FILENAME = re.compile("[\x00-\x1f\x7f\"\\\\]")

#: Printed VERBATIM by every preview. Do not summarise it and do not soften it:
#: the sentence a reader needs is that this was NOT determined, not that it was
#: determined to be small.
BLAST_RADIUS_UNRESOLVED = (
    "UNRESOLVED - this was NOT measured and must not be read as 'contained'. The "
    "bundle names exactly two server-side effects: profile completion is recomputed "
    "(the dispatcher reads profile_completion_percentage off every response), and an "
    "is_resume_updated flag that only the Resume Health Check path touches, which this "
    "is not. Whether Uplers RE-PARSES the resume, RE-SCORES you, NOTIFIES any recruiter, "
    "or affects applications you have ALREADY submitted could not be determined from a "
    "client bundle, and absence of evidence there is not evidence of absence on their "
    "server - that class of effect is exactly the kind that lives server-side."
)

#: The second honesty clause, and the one most likely to be misread as "undo".
SNAPSHOT_RESTORES_BYTES_ONLY = (
    "The snapshot restores the FILE, not the RECORD. Re-uploading it is a fresh upload, "
    "not a revert: server-side identity (file id, created_at) is new, and anything "
    "Uplers DERIVED from the old file - parsed profile fields, a health score, a "
    "tailored variant - is not put back by any local copy."
)

#: The one client-side gate in the bundle this module does NOT reproduce.
PASSWORD_GATE_NOT_CHECKED = (
    "Uplers' own uploader runs an async password-protection precheck before sending "
    "('File is password-protected please upload unprotected file'). This server does "
    "not reproduce it, so an encrypted PDF is refused by Uplers rather than here - as "
    "a 422 on errors.value, after the request has been made."
)


def snapshots_dir() -> Path:
    """Beside `profile_snapshots/`, deliberately NOT inside it.

    `uplers_list_profile_snapshots` globs that directory for `*.json` and reads
    a `skills` count off each record, and `profile_write.load_snapshot` refuses
    any record with no skills in it. Resume records would list there as
    zero-skill rows and refuse on restore - a confusing near-miss rather than a
    clean separation. Two kinds of restore point, two directories.
    """
    path = config.DATA_DIR / "resume_snapshots"
    path.mkdir(parents=True, exist_ok=True)
    return path


# --- reading the live state ------------------------------------------------


def talent_enc_id(payload: Any) -> str:
    """His own `talent_enc_id`, the ONLY parameter the download route takes.

    MEASURED at `talent_details.enc_id` in the captured profile response. It is
    not the same identifier as a requisition's `enc_id` - see
    `endpoints.IDENTIFIER_SPACES` for why this API's reuse of one name across
    identifier spaces is the most likely silent bug in any client of it.

    Refuses rather than returning None: every caller of this is on its way to a
    snapshot, and a snapshot that silently did not happen is the one failure
    this whole module exists to prevent.
    """
    details = payload.get("talent_details") if isinstance(payload, dict) else None
    identifier = details.get("enc_id") if isinstance(details, dict) else None
    if not identifier or not isinstance(identifier, str):
        raise WriteRefused(
            "The profile read carried no talent_details.enc_id, which is the only "
            "parameter the resume download takes. Without it there is no way to "
            "snapshot the current resume, and this server does not replace a resume "
            "it could not first save a copy of. Nothing was sent."
        )
    return identifier


def decode_download(payload: Any) -> dict:
    """`{data, filename, ext, bytes, sha256}` from the download response.

    VERIFIED shape, from all four consumers in the bundle::

        i=e.data.data, a=e.data.blob, s=e.data.ext, l=e.data.filename;
        "pdf"===s?((a=(0,c.i)(a,"application/pdf")).name=l, ...

    and `(0,c.i)` is a base64 decoder (`atob` in 512-byte slices). So `blob` is
    the actual file, base64-encoded, and `ext` and `filename` sit beside it at
    the top level of the body.

    A nested `{"data": {...}}` envelope is accepted as a fallback because
    several routes on this API wrap and this one is read off the response body
    rather than through a redux selector. That is not defensive vagueness: if
    NEITHER shape carries a blob this refuses, and a refusal here blocks the
    write, so an unrecognised envelope fails in the safe direction.
    """
    body = payload if isinstance(payload, dict) else {}
    source = body
    if "blob" not in source:
        nested = body.get("data")
        if isinstance(nested, dict) and "blob" in nested:
            source = nested

    blob = source.get("blob")
    if not blob or not isinstance(blob, str):
        raise WriteRefused(
            "The resume download returned no `blob`, so there is no copy of your "
            "current resume to keep. Uplers has no history, no version list and no "
            "revert - if it were replaced now the old file would be unreachable. "
            "Nothing was sent. Keys seen: %s."
            % (", ".join(sorted(str(key) for key in body)[:12]) or "none")
        )

    try:
        data = base64.b64decode(blob, validate=False)
    except (binascii.Error, ValueError) as exc:
        raise WriteRefused(
            "The resume download's `blob` is not decodable base64 (%s), so the copy "
            "this server would keep is not the file. Refusing to replace a resume it "
            "cannot first save. Nothing was sent." % type(exc).__name__
        ) from exc

    if not data:
        raise WriteRefused(
            "The resume download decoded to zero bytes. Either there is no resume on "
            "the profile yet, or the read failed - and this server cannot tell those "
            "apart, so it refuses. It replaces a resume only when it holds a copy of "
            "the one being replaced. Nothing was sent."
        )

    filename = source.get("filename")
    filename = safe_filename(filename) if isinstance(filename, str) and filename else ""
    ext = source.get("ext")
    ext = str(ext).strip().lower().lstrip(".") if ext else ""
    if ext not in ALLOWED_EXTENSIONS and filename:
        # `ext` is what the bundle switches on, but a missing one is recoverable
        # from the filename, and recovering it is what keeps a good snapshot
        # restorable instead of merely archived.
        ext = Path(filename).suffix.lower().lstrip(".")
    if not filename:
        filename = "resume.%s" % (ext or "bin")

    return {
        "data": data,
        "filename": filename,
        "ext": ext,
        "bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
    }


# --- snapshots -------------------------------------------------------------


def write_snapshot(payload: Any, *, label: str = "auto") -> dict:
    """Persist the CURRENT resume to disk. ALWAYS before a write, never after.

    Ordering is the property, not existence. Uplers' download route takes no
    "which resume" parameter, so a snapshot taken after the replacement returns
    the NEW file and records nothing recoverable.

    Two files per snapshot: the real bytes under their own extension, and a
    JSON sidecar naming them. The bytes are written first and READ BACK before
    the sidecar is written, so a sidecar on disk means the bytes are on disk -
    a half-written snapshot must not be able to look like a whole one.

    `restorable` is returned rather than raised on. Bytes that came back in an
    extension the resume field will not accept are still worth keeping - that
    is the only copy in existence - but they cannot be re-uploaded through this
    route, so the caller is told and is expected to refuse the write.
    """
    record = decode_download(payload)

    clean_label = re.sub(r"[^a-z0-9-]+", "-", str(label).lower()).strip("-") or "auto"
    snapshot_id = "%d-%s" % (int(time.time()), clean_label[:40])
    directory = snapshots_dir()
    suffix = record["ext"] if record["ext"] else "bin"
    blob_path = directory / ("%s.%s" % (snapshot_id, suffix))
    meta_path = directory / ("%s.json" % snapshot_id)

    try:
        blob_path.write_bytes(record["data"])
        written = blob_path.read_bytes()
    except OSError as exc:
        raise WriteRefused(
            policy.relativise_paths(
                "The snapshot could not be written to disk (%s), so there would be no "
                "way back from the replacement. Uplers keeps no previous copy. Nothing "
                "was sent." % exc,
                (blob_path, directory),
            )
        ) from exc

    # Read back rather than trust the write. A short write, a full disk or a
    # sync-on-close failure all produce a file that exists and is wrong, and
    # "the file exists" is the exact claim this precondition must not accept.
    if written != record["data"]:
        raise WriteRefused(
            policy.relativise_paths(
                "The snapshot read back as %d bytes, not the %d that were written, so "
                "the copy on disk is not your resume. Refusing to replace it. Nothing "
                "was sent." % (len(written), record["bytes"]),
                (blob_path,),
            )
        )

    restore_blocked = None
    if record["ext"] not in ALLOWED_EXTENSIONS:
        restore_blocked = (
            "the saved file's extension is %r, and the resume field accepts only %s, "
            "so this copy cannot be re-uploaded through this server"
            % (record["ext"] or "(none)", " or ".join(ALLOWED_EXTENSIONS))
        )
    elif record["bytes"] > MAX_UPLOAD_BYTES:
        restore_blocked = (
            "the saved file is %d KB and the limit is %d KB, so this copy cannot be "
            "re-uploaded through this server"
            % (record["bytes"] // 1024, MAX_UPLOAD_BYTES // 1024)
        )

    meta = {
        "snapshot_id": snapshot_id,
        "taken_at": time.time(),
        "label": clean_label[:40],
        "filename": record["filename"],
        "ext": record["ext"],
        "bytes": record["bytes"],
        "sha256": record["sha256"],
        "blob_file": blob_path.name,
        "restorable": restore_blocked is None,
        "restore_blocked_reason": restore_blocked,
    }
    try:
        meta_path.write_text(
            json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8"
        )
    except OSError as exc:
        raise WriteRefused(
            policy.relativise_paths(
                "The snapshot's bytes were saved but its record could not be written "
                "(%s), so nothing could find them again. Refusing. Nothing was sent."
                % exc,
                (meta_path, blob_path, directory),
            )
        ) from exc

    out = dict(meta)
    # Relativised, not dropped - exactly the trade `profile_write` makes and for
    # the same reason: this path IS the undo handle and the operator is expected
    # to open it. See policy.display_path.
    out["path"] = policy.display_path(str(blob_path))
    out["record_path"] = policy.display_path(str(meta_path))
    return out


def list_snapshots() -> list[dict]:
    """Newest first. One unreadable record must not hide the rest.

    Listing is a read, and an operator hunting for a restore point after a bad
    write is the worst possible moment for the list to raise.
    """
    out: list[dict] = []
    for path in sorted(snapshots_dir().glob("*.json"), reverse=True):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(data, dict):
            continue
        out.append(
            {
                "snapshot_id": data.get("snapshot_id", path.stem),
                "taken_at": data.get("taken_at"),
                "taken_at_iso": stamp_to_iso(data.get("taken_at")),
                "label": data.get("label"),
                "filename": data.get("filename"),
                "ext": data.get("ext"),
                "bytes": data.get("bytes"),
                "sha256": data.get("sha256"),
                "restorable": data.get("restorable"),
                "restore_blocked_reason": data.get("restore_blocked_reason"),
            }
        )
    return out


def load_snapshot(snapshot_id: str | None = None) -> dict:
    """A restore point plus its bytes, refusing anything that is not obviously one.

    `snapshot_id` arrives raw from an agent-callable tool, so it is untrusted
    input naming a file. The guards are the sibling's, in the sibling's order,
    and for the sibling's reason: in the Instahyre server the version without
    them resolved `"../not-a-snapshot"` to a file outside the directory and
    "restored" it over real data.

    The id is validated BEFORE the directory is listed. Ordering it the other
    way round makes the containment guard conditional on the directory being
    non-empty, and a safety check that only runs in some directory states is
    not a safety check.
    """
    if snapshot_id is not None and not SNAPSHOT_ID_RE.fullmatch(str(snapshot_id)):
        raise WriteRefused(
            "%r is not a snapshot id. Ids look like '1755780000-pre-resume-write'. "
            "Call uplers_list_resume_snapshots() to see the real ones."
            % str(snapshot_id)[:60]
        )

    directory = snapshots_dir().resolve()
    available = sorted(directory.glob("*.json"), reverse=True)
    if not available:
        raise WriteRefused(
            "There is no resume snapshot to restore from. One is written automatically "
            "before every resume write, so an empty set means this server has never "
            "replaced your Uplers resume."
        )

    if snapshot_id is None:
        meta_path = available[0]
    else:
        meta_path = (directory / ("%s.json" % snapshot_id)).resolve()
        # Behind the pattern check rather than instead of it: if the pattern is
        # ever loosened, a path that escaped the directory still dies here.
        if meta_path.parent != directory:
            raise WriteRefused(
                "Refusing to read a snapshot from outside the snapshots directory."
            )
        if not meta_path.is_file():
            raise WriteRefused(
                "No resume snapshot %r. Call uplers_list_resume_snapshots()."
                % str(snapshot_id)[:60]
            )

    try:
        record = json.loads(meta_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        # The message is composed around an exception whose filename this server
        # never looks inside; OSError renders it through repr(), so both
        # spellings are scrubbed. Same site as profile_write.load_snapshot.
        raise WriteRefused(
            policy.relativise_paths(
                "Resume snapshot %s could not be read as JSON (%s). Refusing to restore "
                "from a file this server cannot understand - a restore REPLACES the "
                "resume recruiters see." % (meta_path.name, exc),
                (meta_path, directory),
            )
        ) from exc
    if not isinstance(record, dict):
        raise WriteRefused(
            "Resume snapshot %s is not a record this server wrote. Refusing."
            % meta_path.name
        )

    blob_name = record.get("blob_file") or ""
    blob_path = (directory / str(blob_name)).resolve()
    # `blob_file` comes off a JSON file, which is data this process wrote but
    # cannot prove it wrote. It names a file, so it gets the same containment
    # check the id got.
    if not blob_name or blob_path.parent != directory:
        raise WriteRefused(
            "Resume snapshot %s names its file as %r, which is not inside the "
            "snapshots directory. Refusing." % (meta_path.name, str(blob_name)[:60])
        )
    try:
        data = blob_path.read_bytes()
    except OSError as exc:
        raise WriteRefused(
            policy.relativise_paths(
                "Resume snapshot %s has a record but its bytes could not be read (%s). "
                "There is nothing to restore. Nothing was sent."
                % (meta_path.name, exc),
                (blob_path, meta_path, directory),
            )
        ) from exc

    if not data:
        raise WriteRefused(
            "Resume snapshot %s holds zero bytes. Restoring it would not put anything "
            "back - it would replace the resume recruiters see with an empty file. "
            "Refusing." % meta_path.name
        )

    expected = record.get("sha256")
    actual = hashlib.sha256(data).hexdigest()
    if expected and expected != actual:
        raise WriteRefused(
            "Resume snapshot %s does not match its own checksum, so the file on disk "
            "is not the one that was saved. Refusing to upload it." % meta_path.name
        )

    ext = str(record.get("ext") or "").strip().lower().lstrip(".")
    if ext not in ALLOWED_EXTENSIONS:
        raise WriteRefused(
            "Resume snapshot %s is a %r file and the resume field accepts only %s. Its "
            "bytes are still on disk and can be uploaded through Uplers' own site, but "
            "this server will not send them."
            % (meta_path.name, ext or "(none)", " or ".join(ALLOWED_EXTENSIONS))
        )
    if len(data) > MAX_UPLOAD_BYTES:
        raise WriteRefused(
            "Resume snapshot %s is %d KB and the limit is %d KB, so Uplers would reject "
            "it. Nothing was sent."
            % (meta_path.name, len(data) // 1024, MAX_UPLOAD_BYTES // 1024)
        )

    out = dict(record)
    out["data"] = data
    out["bytes"] = len(data)
    out["sha256"] = actual
    out["filename"] = safe_filename(record.get("filename") or ("resume.%s" % ext))
    out["ext"] = ext
    out["path"] = policy.display_path(str(blob_path))
    out["taken_at_iso"] = stamp_to_iso(record.get("taken_at"))
    return out


# --- the file going up -----------------------------------------------------


def safe_filename(name: Any) -> str:
    """The basename, with anything that could break a multipart header removed.

    The filename is written into a `Content-Disposition` header. A quote, a
    backslash or a control character there ends the header early or starts a
    new one, and the value arrives from a snapshot record or from a caller's
    path, neither of which this module controls.
    """
    text = Path(str(name or "")).name
    text = _UNSAFE_IN_FILENAME.sub("", text).strip()
    return text or "resume"


def read_upload(file_path: Any) -> dict:
    """The new resume, or a refusal naming the precondition that failed.

    Four gates, in the order that makes each one provable on its own and that
    puts the cheapest first: a rejected file must cost zero requests, so all of
    this runs before the caller touches the network.

    Uplers' own text is quoted where it exists, so a refusal here reads the
    same as a refusal there.
    """
    raw = str(file_path or "").strip()
    if not raw:
        raise WriteRefused("No file was named. Nothing was sent.")

    path = Path(raw).expanduser()
    if not path.exists():
        raise WriteRefused(
            policy.relativise_paths(
                "There is no file at %s. Nothing was sent." % path, (path,)
            )
        )
    if not path.is_file():
        raise WriteRefused(
            policy.relativise_paths("%s is not a file. Nothing was sent." % path, (path,))
        )

    ext = path.suffix.lower().lstrip(".")
    if ext not in ALLOWED_EXTENSIONS:
        raise WriteRefused(
            "%s is a %r file. Uplers' own message is 'The resume must be a file of "
            "type: pdf, docx.' and its uploader accepts nothing else. Nothing was sent."
            % (path.name, ext or "(no extension)")
        )

    try:
        data = path.read_bytes()
    except OSError as exc:
        raise WriteRefused(
            policy.relativise_paths(
                "%s could not be read (%s). Nothing was sent." % (path.name, exc),
                (path,),
            )
        ) from exc

    if not data:
        raise WriteRefused(
            "%s is empty. Uplers' own message is 'Please add your resume'. Nothing was "
            "sent." % path.name
        )
    if len(data) > MAX_UPLOAD_BYTES:
        raise WriteRefused(
            "%s is %d KB. Uplers refuses anything over %d KB ('File size should be less "
            "than 2 MB'), and their check is size/1024 > 2048. Nothing was sent."
            % (path.name, len(data) // 1024, MAX_UPLOAD_BYTES // 1024)
        )

    return {
        "data": data,
        "filename": safe_filename(path.name),
        "ext": ext,
        "bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
        "path": policy.display_path(str(path)),
    }


def multipart_parts(filename: Any, data: bytes, ext: Any) -> dict:
    """The EXACT httpx `files=` mapping for the profile-page write. Two parts.

    Mirrors the bundle append-for-append and in the bundle's order, which
    insertion-ordered dicts preserve on the wire::

        n.append("field","resume")   ->  "field": (None, "resume")
        n.append("value", <File>)    ->  "value": (name, bytes, mime)

    `(None, "resume")` is how httpx renders a plain form field with no filename,
    which is what a browser sends for `FormData.append(k, v)` on a string - the
    same rendering `TalentClient.post_form` already relies on for the apply
    route. The value part carries a filename and a Content-Type because there
    it is a File.

    **No third part is built, ever.** `tid` would aim the write at somebody
    else's profile; the other two names in NEVER_SENT belong to the two write
    paths this deliberately does not implement. The mapping is constructed here
    in full rather than merged from an argument, so there is no parameter
    through which a fourth part could arrive.
    """
    key = str(ext or "").strip().lower().lstrip(".")
    if key not in CONTENT_TYPES:
        raise WriteRefused(
            "No content type for a %r resume; only %s are accepted. Nothing was sent."
            % (key or "(none)", " and ".join(ALLOWED_EXTENSIONS))
        )
    if not isinstance(data, (bytes, bytearray)) or not data:
        raise WriteRefused("The resume part would carry no bytes. Nothing was sent.")
    return {
        PART_FIELD: (None, FIELD_RESUME),
        PART_VALUE: (safe_filename(filename), bytes(data), CONTENT_TYPES[key]),
    }


# --- what the preview has to say -------------------------------------------


def replacement_warning(filename: Any) -> str:
    """The one sentence a reader must not be able to skim past."""
    return (
        "PERMANENT REPLACEMENT. %s becomes the resume every Uplers recruiter sees, and "
        "Uplers keeps NO previous copy: there is no history, no version list, no "
        "archive and no revert route anywhere in their product. The pre-flight snapshot "
        "this server takes is the ONLY way back, and it only exists because it is taken "
        "BEFORE the write - their download route has no 'which resume' parameter, so "
        "afterwards it returns the new file." % safe_filename(filename)
    )


def preview_notes(filename: Any) -> list[str]:
    """The full honesty block. Every preview prints all of it, in this order."""
    return [
        replacement_warning(filename),
        SNAPSHOT_RESTORES_BYTES_ONLY,
        "Blast radius: " + BLAST_RADIUS_UNRESOLVED,
        PASSWORD_GATE_NOT_CHECKED,
    ]


def stamp_to_iso(stamp: Any) -> str | None:
    """Snapshot timestamps are unix floats on disk; a reader wants a date."""
    if stamp is None:
        return None
    try:
        return datetime.fromtimestamp(float(stamp), timezone.utc).isoformat(
            timespec="seconds"
        )
    except (OSError, OverflowError, ValueError, TypeError):
        return None


# --- the sender seam -------------------------------------------------------


def sender_for(client: Any, path: str):
    """The one callable that can put a resume on the wire. Built by `server.py`.

    TWO THINGS THIS EXISTS TO SOLVE, and the second is a wart worth naming.

    1.  It is the seam that makes "no write happened" a STRUCTURAL claim rather
        than an observational one. The orchestrators below cannot send without
        one of these, so a test proving the sender was never called is proving
        something about control flow, not about what a mock transport happened
        to see.

    2.  `TalentClient` has no public verb for a multipart body carrying FILE
        BYTES. `post_form` is multipart, but it renders every value as
        ``(None, str(value))`` - correct for the apply route's scalar fields
        and destructive here, since ``str(b"%PDF...")`` is a repr, not the
        file. So this reaches for the client's own request path directly.
        **The clean home for this is a `post_multipart` verb on `TalentClient`**
        and this function should become a two-line call to it; that edit was
        out of scope for the wave that wrote this file.

    `path` is attached to the returned callable so a preview can print the
    endpoint it would hit without this module having to name a route constant
    it is deliberately not allowed to know.
    """

    async def send(parts):
        return await client._request("POST", path, files=parts)

    send.path = path
    return send


def _endpoint_of(send: Any) -> str | None:
    return getattr(send, "path", None)


def _require_sender(send: Any) -> None:
    if send is None or not callable(send):
        raise WriteRefused(
            "This write was called with no sender, so there is nothing it could put on "
            "the wire. That is deliberate: the resume write is built so it cannot fire "
            "without the caller supplying the route. Nothing was sent."
        )


def _describe_parts(parts: dict) -> dict:
    """The multipart body as a reader can check it, WITHOUT the bytes.

    A preview must show the shape - which parts, what the field says, that
    `tid` is absent - and must not carry a resume through the response. So the
    file part renders as a description and the scalar part renders verbatim.
    """
    out: dict = {}
    for name, part in parts.items():
        filename, content = part[0], part[1]
        if filename is None:
            out[name] = content
        else:
            out[name] = "<%d bytes, filename %r, %s>" % (
                len(content),
                filename,
                part[2] if len(part) > 2 else "no content type",
            )
    return out


# --- the two write orchestrators -------------------------------------------


async def replace_resume(
    client: Any,
    file_path: Any,
    *,
    confirm: bool = False,
    send: Any = None,
) -> dict:
    """Replace the profile resume. Previews and performs NOTHING unless confirmed.

    The order of the steps IS the safety design, so it is spelled out rather
    than left to be read off the code:

    1.  Validate the local file. Cheapest gate, and it runs before any network
        call, so a wrong extension or an oversized file costs zero requests.
    2.  Read the profile for `talent_enc_id` - the download route's only
        parameter.
    3.  Read the CURRENT resume and decode it. A download that returns nothing
        decodable refuses here, before anything is written and before anything
        is sent.
    4.  If `confirm` is False, return the preview. No snapshot is written and
        no request is sent - matching `uplers_apply` and `uplers_dismiss`,
        which perform nothing without a confirm.
    5.  Persist the snapshot and read it back off disk. **A snapshot that
        cannot be written, or that lands unrestorable, refuses the write.**
        This is the hard precondition, not a warning: Uplers has no revert, so
        a replacement without a saved copy is a one-way door.
    6.  Only now, send.
    """
    upload = read_upload(file_path)

    payload = await client.get_json(endpoints.EP_PROFILE)
    identifier = talent_enc_id(payload)
    download = await client.get_json(EP_DOWNLOAD_RESUME, {"talent_id": identifier})
    current = decode_download(download)

    parts = multipart_parts(upload["filename"], upload["data"], upload["ext"])
    common = {
        "action": "replace_resume",
        "method": "POST multipart/form-data",
        "endpoint": _endpoint_of(send),
        "parts": _describe_parts(parts),
        "new_file": {
            "filename": upload["filename"],
            "ext": upload["ext"],
            "bytes": upload["bytes"],
            "sha256": upload["sha256"],
            "path": upload["path"],
        },
        "current_resume": {
            "filename": current["filename"],
            "ext": current["ext"],
            "bytes": current["bytes"],
            "sha256": current["sha256"],
        },
        "notes": preview_notes(upload["filename"]),
    }

    if not confirm:
        result = dict(common)
        result["performed"] = False
        result["snapshot"] = {
            "written": False,
            "available": True,
            "bytes": current["bytes"],
            "filename": current["filename"],
            "ext": current["ext"],
            "restorable": current["ext"] in ALLOWED_EXTENSIONS
            and current["bytes"] <= MAX_UPLOAD_BYTES,
        }
        # `upload["path"]` and NOT the raw `file_path`: this string is echoed
        # into a tool response, and the caller's argument is an absolute local
        # path. Echoing it back publishes this box's directory layout into any
        # shared transcript - caught by this module's own leak test, which is
        # the second time a to_confirm/undo handle has been the leak site in
        # this server (see policy.display_path).
        result["to_confirm"] = "uplers_replace_resume(%r, confirm=True)" % upload["path"]
        result["notes"].insert(
            0,
            "PREVIEW - nothing was sent and no snapshot was written. Your current "
            "resume (%s, %d KB) was read back successfully, so a restore point CAN be "
            "taken; confirming writes it to disk first and only then sends."
            % (current["filename"], current["bytes"] // 1024),
        )
        return result

    # The sender is checked BEFORE the snapshot is written, so a call that could
    # never have sent anything does not leave a restore point behind for a write
    # that was never going to happen.
    _require_sender(send)

    snapshot = write_snapshot(download, label="pre-resume-write")
    if not snapshot["restorable"]:
        raise WriteRefused(
            "Your current resume WAS saved to %s, but %s. Replacing it now would leave "
            "you with a copy this server cannot put back, and Uplers has no revert. "
            "Nothing was sent."
            % (snapshot["path"], snapshot["restore_blocked_reason"])
        )

    response = await send(parts)

    result = dict(common)
    result["performed"] = True
    result["snapshot"] = dict(snapshot, written=True)
    result["undo"] = "uplers_restore_resume(snapshot_id=%r, confirm=True)" % snapshot[
        "snapshot_id"
    ]
    result["response"] = response if isinstance(response, dict) else {}
    result["notes"].append(
        "Your previous resume is at %s (%d KB, sha256 %s). It is the only copy that "
        "exists - Uplers no longer holds it."
        % (snapshot["path"], snapshot["bytes"] // 1024, snapshot["sha256"][:16])
    )
    return result


async def restore_resume(
    client: Any,
    snapshot_id: Any = None,
    *,
    confirm: bool = False,
    send: Any = None,
) -> dict:
    """Put a snapshotted resume back. Previews and performs NOTHING unless confirmed.

    This is the half that makes the replacement reversible, so it is not
    optional and it is guarded exactly as hard as the thing it undoes - a
    restore IS a replacement write, and one aimed at the wrong snapshot is the
    obvious way to lose the current file. So it takes its own snapshot of the
    CURRENT resume first, the same way `uplers_restore_profile` writes a
    `pre-restore` record before sending.
    """
    record = load_snapshot(snapshot_id)

    payload = await client.get_json(endpoints.EP_PROFILE)
    identifier = talent_enc_id(payload)
    download = await client.get_json(EP_DOWNLOAD_RESUME, {"talent_id": identifier})
    current = decode_download(download)

    parts = multipart_parts(record["filename"], record["data"], record["ext"])
    common = {
        "action": "restore_resume",
        "method": "POST multipart/form-data",
        "endpoint": _endpoint_of(send),
        "parts": _describe_parts(parts),
        "restoring": {
            "snapshot_id": record.get("snapshot_id"),
            "taken_at": record.get("taken_at_iso"),
            "filename": record["filename"],
            "ext": record["ext"],
            "bytes": record["bytes"],
            "sha256": record["sha256"],
            "path": record["path"],
        },
        "current_resume": {
            "filename": current["filename"],
            "ext": current["ext"],
            "bytes": current["bytes"],
            "sha256": current["sha256"],
        },
        "already_current": record["sha256"] == current["sha256"],
        "notes": preview_notes(record["filename"]),
    }

    if not confirm:
        result = dict(common)
        result["performed"] = False
        result["to_confirm"] = "uplers_restore_resume(snapshot_id=%r, confirm=True)" % (
            record.get("snapshot_id")
        )
        result["notes"].insert(
            0,
            "PREVIEW - nothing was sent. This would replace the resume Uplers holds "
            "now (%s, %d KB) with snapshot %s (%s, %d KB). It is a replacement write, "
            "not a revert, so it is as destructive as the write it undoes."
            % (
                current["filename"],
                current["bytes"] // 1024,
                record.get("snapshot_id"),
                record["filename"],
                record["bytes"] // 1024,
            ),
        )
        return result

    _require_sender(send)

    # The pre-restore state is itself worth keeping: without this, a restore
    # aimed at the wrong snapshot would have nothing to come back to.
    pre = write_snapshot(download, label="pre-resume-restore")

    response = await send(parts)

    result = dict(common)
    result["performed"] = True
    result["snapshot"] = dict(pre, written=True)
    result["undo"] = "uplers_restore_resume(snapshot_id=%r, confirm=True)" % pre[
        "snapshot_id"
    ]
    result["response"] = response if isinstance(response, dict) else {}
    result["notes"].append(
        "The resume this replaced was saved first, as snapshot %s (%s)."
        % (pre["snapshot_id"], pre["path"])
    )
    return result
