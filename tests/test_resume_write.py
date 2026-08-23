"""The resume write: every guard, and the two that carry the whole design.

This suite exists because the resume write is the only one-way door in this
server that acts on a FILE. Uplers keeps no previous copy - VERIFIED absences
across their whole production bundle (`resume_history`, `resume_versions`,
`previous_resume`, `old_resume`, `resume_archive`: 0 hits each) and their
download route takes no "which resume" parameter, so it always returns the
CURRENT one. Miss the pre-flight snapshot and the old document is unreachable
forever. Evidence: `_audit/_slices/_slice-resume-write-shape.md`.

Two properties here are load-bearing and everything else is support:

  1.  **No confirm means no request.** Same idiom as `uplers_apply` and
      `uplers_dismiss`, which perform nothing unless `confirm=True`.
  2.  **No snapshot means no write.** A hard precondition, not a warning, and
      an ORDERED one - the bytes must be on disk before the request leaves.

Both were shown FAILING with the guard deliberately removed before being
counted; the red output is recorded in
`_audit/_slices/_slice-resume-write-build.md`. A guard whose test cannot fail
is not a guard.

NO NETWORK, ever. Every request goes through httpx.MockTransport and every
fixture is synthetic - there is no captured resume in this repository and this
suite does not create one. `isolated_snapshots` is autouse so a test cannot
write a restore point into the real data directory by forgetting a fixture.
"""

from __future__ import annotations

import base64
import json
import re
from pathlib import Path

import httpx
import pytest

from conftest import make_transport
from uplers_server import endpoints, resume_write
from uplers_server.profile_write import WriteRefused
from uplers_server.talent import TalentClient

PROFILE_PATH = "/api/" + endpoints.EP_PROFILE
DOWNLOAD_PATH = "/api/" + resume_write.EP_DOWNLOAD_RESUME
UPSERT_PATH = "/api/" + endpoints.EP_PROFILE_UPSERT

TOKEN = "42|bearer-token-that-must-never-be-printed"

#: His talent_enc_id lives at `talent_details.enc_id`; this is a synthetic one
#: of the same shape and length. Nothing real appears in this file.
ENC_ID = "VEVTVC1FTkMtSUQtMDAwMDAwMDA9PQ=="

#: Synthetic file bodies. Nothing parses them - the gates are extension, size
#: and emptiness - so a plausible magic number plus filler is the whole
#: requirement, and using a real resume would put one in the repository.
PDF_BYTES = b"%PDF-1.4\n1 0 obj<</Type/Catalog>>endobj\n%%EOF\n"
DOCX_BYTES = b"PK\x03\x04\x14\x00\x00\x00\x08\x00synthetic-docx-body"


# --- wiring ----------------------------------------------------------------
#
# Deliberately local rather than imported from `test_talent_tools`, which the
# sibling write suite does. The orchestrators under test take a client as an
# argument instead of building one, so there is nothing to monkeypatch, and a
# local six-line factory is a smaller thing to keep working than a cross-file
# import of another suite's helpers.


def client_over(handler):
    """(TalentClient, calls) over a MockTransport. `calls` is the risk surface."""
    transport, calls = make_transport(handler)
    return TalentClient(lambda: TOKEN, transport=transport, delay=0), calls


def writes(calls):
    """Every request that was not a read. A write tool's whole risk surface."""
    return [call for call in calls if call.method != "GET"]


def upserts(calls):
    return [call for call in calls if call.url.path == UPSERT_PATH]


class Recorder:
    """A sender that records and never sends.

    The confirm gate and the snapshot precondition are claims about CONTROL
    FLOW, so they are asserted on the seam itself as well as on the transport:
    "the sender was never called" cannot be satisfied by a request that went
    somewhere the mock was not watching.
    """

    def __init__(self, response=None):
        self.calls = []
        self._response = response if response is not None else {"data": "resume.pdf"}

    async def __call__(self, parts):
        self.calls.append(parts)
        return self._response


def profile_body(enc_id=ENC_ID):
    details = {"id": 1, "enc_id": enc_id} if enc_id is not None else {"id": 1}
    return {"talent_details": details, "masters": {}}


def download_body(data=PDF_BYTES, filename="Jane_Doe_Resume.pdf", ext="pdf", blob=None):
    """The measured envelope: base64 `blob` beside a plain `ext` and `filename`.

    `blob` overrides the encoding, because the two empty cases are DIFFERENT
    guards and only one of them is reachable by encoding empty bytes:
    ``b64encode(b"") == ""`` is falsy, so it trips the missing-blob check. A
    blob that is PRESENT and decodes to nothing has to be supplied directly.
    """
    body = {"blob": base64.b64encode(data).decode("ascii") if blob is None else blob}
    if ext is not None:
        body["ext"] = ext
    if filename is not None:
        body["filename"] = filename
    return body


def routes(profile=None, download=None, upsert=None, on_upsert=None):
    """Route the three paths this write touches; anything else is a 404.

    A 404 rather than a friendly default on purpose: a request to a route this
    write has no business making should show up as a failure, not as a pass.
    """

    def handler(request):
        if request.url.path == PROFILE_PATH:
            return httpx.Response(200, json=profile if profile is not None else profile_body())
        if request.url.path == DOWNLOAD_PATH:
            return httpx.Response(
                200, json=download if download is not None else download_body()
            )
        if request.url.path == UPSERT_PATH:
            if on_upsert is not None:
                on_upsert(request)
            return httpx.Response(200, json=upsert or {"data": "Jane_Doe_Resume.pdf"})
        return httpx.Response(404, json={"message": "unrouted: %s" % request.url.path})

    return handler


# --- fixtures --------------------------------------------------------------


@pytest.fixture(autouse=True)
def isolated_snapshots(monkeypatch, tmp_path):
    """Snapshots go to tmp_path. Autouse: a test must not be able to write a
    copy of a real resume into the operator's data directory by forgetting."""
    directory = tmp_path / "resume_snapshots"
    directory.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(resume_write, "snapshots_dir", lambda: directory)
    return directory


@pytest.fixture
def new_resume(tmp_path):
    """A factory for the file going UP. Defaults to a valid small pdf."""

    def build(name="Jane_Doe_New_Resume.pdf", data=PDF_BYTES):
        path = tmp_path / name
        path.write_bytes(data)
        return path

    return build


def snapshot_files(directory):
    return sorted(path.name for path in directory.iterdir())


def part_names(request):
    """The multipart part names, in wire order.

    The lookbehind is not decoration: `filename="..."` also ends in `name="`,
    so an unanchored hunt reports the uploaded file's own name as a third part
    and the "exactly two parts" assertion fails for the wrong reason. Measured,
    not predicted - that is exactly how this helper failed on its first run.
    """
    return re.findall(r'(?<!file)name="([^"]+)"', request.content.decode("latin-1"))


# ===========================================================================
# 1. THE CONFIRM GATE - no confirm means no request
# ===========================================================================


async def test_without_confirm_nothing_is_sent_and_the_sender_is_never_called(
    new_resume, isolated_snapshots
):
    """The first of the two load-bearing guards.

    Asserted three ways because they fail in different directions: the seam
    (the sender object), the transport (any non-GET), and the route (an upsert
    by any path). A write that slipped past one of those would still be caught.

    ORDER MATTERS HERE, and it is not style. `performed is False` was written
    first and the planted control proved it a bad choice: with the gate removed
    that assertion fires and the test stops, so the red output said
    "assert True is False" and never reached the question anyone cares about.
    The claims about whether a REQUEST HAPPENED now report first, so the
    failure names the damage rather than a flag describing it.
    """
    client, calls = client_over(routes())
    sender = Recorder()

    result = await resume_write.replace_resume(
        client, str(new_resume()), confirm=False, send=sender
    )

    assert sender.calls == []
    assert writes(calls) == []
    assert upserts(calls) == []
    assert result["performed"] is False
    await client.aclose()


async def test_without_confirm_no_snapshot_is_written_either(
    new_resume, isolated_snapshots
):
    """A preview that leaves a restore point behind is lying about performing
    nothing, and it would litter the directory a real restore has to search."""
    client, _ = client_over(routes())

    await resume_write.replace_resume(
        client, str(new_resume()), confirm=False, send=Recorder()
    )

    assert snapshot_files(isolated_snapshots) == []
    await client.aclose()


async def test_the_preview_shows_the_endpoint_and_the_exact_parts(new_resume):
    """A preview that does not show the body is not a preview.

    The caller is being asked to authorise replacing a document. `parts` is the
    decision, so it is rendered - minus the bytes, which must not ride back
    through a tool response.
    """
    client, _ = client_over(routes())
    sender = resume_write.sender_for(client, endpoints.EP_PROFILE_UPSERT)

    result = await resume_write.replace_resume(
        client, str(new_resume()), confirm=False, send=sender
    )

    assert result["method"] == "POST multipart/form-data"
    assert result["endpoint"] == endpoints.EP_PROFILE_UPSERT
    assert result["parts"]["field"] == "resume"
    assert "application/pdf" in result["parts"]["value"]
    assert "tid" not in result["parts"]
    # The bytes themselves never appear in a result.
    assert "%PDF" not in json.dumps(result)
    await client.aclose()


async def test_the_preview_says_plainly_what_this_costs(new_resume):
    """The four sentences the operator has to read before confirming.

    Pinned as claims rather than as wording where possible, but three of these
    ARE the wording: 'recruiters see', 'no previous copy', 'only way back' and
    'UNRESOLVED' are the load-bearing phrases, and a rewrite that drops one of
    them has changed what the tool tells him.
    """
    client, _ = client_over(routes())

    result = await resume_write.replace_resume(
        client, str(new_resume()), confirm=False, send=Recorder()
    )
    prose = " ".join(result["notes"])

    assert "recruiter" in prose.lower()               # who sees it
    assert "NO previous copy" in prose                # Uplers keeps nothing
    assert "ONLY way back" in prose                   # the snapshot is it
    assert "UNRESOLVED" in prose                      # the blast radius
    assert "not the RECORD" in prose                  # bytes, not derived state
    assert "re-parses" in prose.lower() or "RE-PARSES" in prose
    await client.aclose()


async def test_the_preview_does_not_call_the_blast_radius_safe(new_resume):
    """The honesty requirement, as a negative.

    'Nothing in the bundle names such an effect' is true and is NOT 'safe'.
    Absence of evidence in a client bundle is not evidence of absence on a
    server, and the note must not be softened into the second claim.
    """
    client, _ = client_over(routes())

    result = await resume_write.replace_resume(
        client, str(new_resume()), confirm=False, send=Recorder()
    )
    prose = " ".join(result["notes"]).lower()

    assert "absence of evidence" in prose
    assert "not measured" in prose
    for softener in ("is safe", "is contained", "no side effects", "harmless"):
        assert softener not in prose, "the preview soft-pedals an unresolved blast radius"
    await client.aclose()


# ===========================================================================
# 2. THE SNAPSHOT PRECONDITION - no snapshot means no write
# ===========================================================================


async def test_a_download_with_no_blob_stops_the_write(new_resume, isolated_snapshots):
    """The second load-bearing guard.

    An answer that carries no file is indistinguishable from a read that
    failed, and this server replaces a resume only when it holds a copy of the
    one being replaced.
    """
    client, calls = client_over(routes(download={"message": "ok"}))
    sender = Recorder()

    with pytest.raises(WriteRefused) as caught:
        await resume_write.replace_resume(
            client, str(new_resume()), confirm=True, send=sender
        )

    assert "no copy of your current resume" in str(caught.value)
    assert sender.calls == []
    assert writes(calls) == []
    assert snapshot_files(isolated_snapshots) == []
    await client.aclose()


async def test_a_download_that_decodes_to_zero_bytes_stops_the_write(
    new_resume, isolated_snapshots
):
    """An empty blob is 'no resume yet' OR 'the read failed', and this server
    cannot tell those apart - so it refuses rather than guessing the safe one."""
    client, calls = client_over(routes(download=download_body(blob="\n")))
    sender = Recorder()

    with pytest.raises(WriteRefused) as caught:
        await resume_write.replace_resume(
            client, str(new_resume()), confirm=True, send=sender
        )

    assert "zero bytes" in str(caught.value)
    assert sender.calls == []
    assert writes(calls) == []
    await client.aclose()


async def test_a_snapshot_that_cannot_reach_the_disk_stops_the_write(
    monkeypatch, new_resume, isolated_snapshots
):
    """'The snapshot failed' includes 'the disk refused it'.

    A full disk, a read-only directory and a permissions change all land here,
    and all three mean the same thing: there would be no way back.
    """

    # Create the upload BEFORE the patch. `new_resume` writes it with the very
    # method this test is about to break, and a fixture dying of the injected
    # fault would pass this test for entirely the wrong reason - which is what
    # it did on the first run.
    upload = str(new_resume())

    def boom(self, data):
        raise OSError("simulated: no space left on device")

    monkeypatch.setattr(Path, "write_bytes", boom)

    client, calls = client_over(routes())
    sender = Recorder()

    with pytest.raises(WriteRefused) as caught:
        await resume_write.replace_resume(client, upload, confirm=True, send=sender)

    assert "could not be written to disk" in str(caught.value)
    assert sender.calls == []
    assert writes(calls) == []
    await client.aclose()


async def test_a_snapshot_that_reads_back_wrong_stops_the_write(
    monkeypatch, new_resume, isolated_snapshots
):
    """A file that exists and is WRONG is the failure a bare `.exists()` misses.

    Short writes and sync-on-close failures both produce one, and 'the file
    exists' is the exact claim this precondition must not accept.
    """
    real_read = Path.read_bytes

    def truncated(self):
        data = real_read(self)
        return data[:-1] if self.parent == isolated_snapshots else data

    monkeypatch.setattr(Path, "read_bytes", truncated)

    client, calls = client_over(routes())
    sender = Recorder()

    with pytest.raises(WriteRefused) as caught:
        await resume_write.replace_resume(
            client, str(new_resume()), confirm=True, send=sender
        )

    assert "read back as" in str(caught.value)
    assert sender.calls == []
    assert writes(calls) == []
    await client.aclose()


async def test_the_snapshot_is_on_disk_BEFORE_the_request_leaves(
    new_resume, isolated_snapshots
):
    """Ordering, not existence, is the property.

    Uplers' download route takes no version parameter, so a snapshot written
    after the replacement records the NEW file. This asserts from inside the
    transport, at the only moment where the question has an answer.
    """
    seen = {}

    def on_upsert(request):
        seen["files"] = snapshot_files(isolated_snapshots)

    client, calls = client_over(routes(on_upsert=on_upsert))
    sender = resume_write.sender_for(client, endpoints.EP_PROFILE_UPSERT)

    result = await resume_write.replace_resume(
        client, str(new_resume()), confirm=True, send=sender
    )

    assert result["performed"] is True
    assert len(upserts(calls)) == 1
    # Both halves already present when the request was served: the bytes and
    # the record that can find them again.
    assert len(seen["files"]) == 2
    assert any(name.endswith(".pdf") for name in seen["files"])
    assert any(name.endswith(".json") for name in seen["files"])
    await client.aclose()


async def test_an_unrestorable_snapshot_is_kept_but_the_write_is_refused(
    new_resume, isolated_snapshots
):
    """The one case where the bytes are saved AND the write still refuses.

    A `.doc` resume cannot go back up through a field whose own gate is
    'pdf, docx'. Throwing the bytes away would destroy the only copy in
    existence, so they are kept - but a copy that cannot be re-uploaded is not
    a rollback, and the write does not proceed on one.
    """
    client, calls = client_over(
        routes(download=download_body(filename="Jane_Doe_Resume.doc", ext="doc"))
    )
    sender = Recorder()

    with pytest.raises(WriteRefused) as caught:
        await resume_write.replace_resume(
            client, str(new_resume()), confirm=True, send=sender
        )

    assert "cannot put back" in str(caught.value)
    assert sender.calls == []
    assert writes(calls) == []
    # The bytes survived. That is the point of refusing here rather than at
    # decode time.
    kept = snapshot_files(isolated_snapshots)
    assert any(name.endswith(".doc") for name in kept)
    await client.aclose()


async def test_a_profile_with_no_enc_id_stops_the_write(new_resume):
    """`talent_id` is the download route's ONLY parameter. Without it there is
    no snapshot, and therefore no write."""
    client, calls = client_over(routes(profile=profile_body(enc_id=None)))
    sender = Recorder()

    with pytest.raises(WriteRefused) as caught:
        await resume_write.replace_resume(
            client, str(new_resume()), confirm=True, send=sender
        )

    assert "enc_id" in str(caught.value)
    assert sender.calls == []
    assert writes(calls) == []
    await client.aclose()


async def test_a_confirmed_write_with_no_sender_refuses_before_snapshotting(
    new_resume, isolated_snapshots
):
    """The seam, asserted as a seam.

    This module cannot send by itself; `server.py` hands it the route. The
    check runs BEFORE the snapshot so a call that could never have sent
    anything does not leave a restore point behind for a write that was never
    going to happen.
    """
    client, calls = client_over(routes())

    with pytest.raises(WriteRefused) as caught:
        await resume_write.replace_resume(client, str(new_resume()), confirm=True)

    assert "no sender" in str(caught.value)
    assert writes(calls) == []
    assert snapshot_files(isolated_snapshots) == []
    await client.aclose()


# ===========================================================================
# 3. VALIDATION - and each rejection costs zero requests
# ===========================================================================


async def test_a_txt_file_is_refused_and_costs_zero_requests(tmp_path):
    """Uplers' own message, quoted, and the gate runs before any network call."""
    path = tmp_path / "Jane_Doe_Resume.txt"
    path.write_text("not a resume Uplers will take", encoding="utf-8")
    client, calls = client_over(routes())
    sender = Recorder()

    with pytest.raises(WriteRefused) as caught:
        await resume_write.replace_resume(client, str(path), confirm=True, send=sender)

    assert "must be a file of type: pdf, docx" in str(caught.value)
    assert calls == []          # not merely no writes - NO requests at all
    assert sender.calls == []
    await client.aclose()


async def test_a_file_over_two_megabytes_is_refused_and_costs_zero_requests(tmp_path):
    """Their gate is `size/1024 > 2048`. One byte past it is past it."""
    path = tmp_path / "Jane_Doe_Big.pdf"
    path.write_bytes(b"%PDF-1.4\n" + b"0" * (resume_write.MAX_UPLOAD_BYTES))
    client, calls = client_over(routes())

    with pytest.raises(WriteRefused) as caught:
        await resume_write.replace_resume(
            client, str(path), confirm=True, send=Recorder()
        )

    assert "2048 KB" in str(caught.value)
    assert calls == []
    await client.aclose()


async def test_a_file_of_exactly_two_megabytes_is_accepted(tmp_path, isolated_snapshots):
    """The boundary, mirrored to the byte.

    Their check rejects on `size/1024 > 2048`, so 2097152 bytes is ACCEPTED.
    A client guard that is stricter than the server's refuses uploads the
    platform would have taken.
    """
    path = tmp_path / "Jane_Doe_Exact.pdf"
    path.write_bytes(b"0" * resume_write.MAX_UPLOAD_BYTES)
    client, calls = client_over(routes())
    sender = resume_write.sender_for(client, endpoints.EP_PROFILE_UPSERT)

    result = await resume_write.replace_resume(
        client, str(path), confirm=True, send=sender
    )

    assert result["performed"] is True
    assert result["new_file"]["bytes"] == 2097152
    assert len(upserts(calls)) == 1
    await client.aclose()


async def test_a_missing_file_is_refused_and_costs_zero_requests(tmp_path):
    client, calls = client_over(routes())

    with pytest.raises(WriteRefused) as caught:
        await resume_write.replace_resume(
            client, str(tmp_path / "nope.pdf"), confirm=True, send=Recorder()
        )

    assert "no file at" in str(caught.value)
    assert calls == []
    await client.aclose()


async def test_an_empty_file_is_refused_and_costs_zero_requests(tmp_path):
    path = tmp_path / "Jane_Doe_Empty.pdf"
    path.write_bytes(b"")
    client, calls = client_over(routes())

    with pytest.raises(WriteRefused) as caught:
        await resume_write.replace_resume(
            client, str(path), confirm=True, send=Recorder()
        )

    assert "Please add your resume" in str(caught.value)
    assert calls == []
    await client.aclose()


async def test_a_directory_is_refused(tmp_path):
    client, calls = client_over(routes())

    with pytest.raises(WriteRefused):
        await resume_write.replace_resume(
            client, str(tmp_path), confirm=True, send=Recorder()
        )

    assert calls == []
    await client.aclose()


def test_a_filename_cannot_break_the_multipart_header():
    """The filename lands in a Content-Disposition header, and it comes from a
    path or a snapshot record - neither of which this module controls.

    Asserted as the PROPERTY - no character survives that can end the header
    early or start a new one - rather than as an exact output string. The
    sanitiser strips the dangerous characters and keeps the rest, which is the
    right behaviour: guessing what a hostile filename "meant" is how a
    sanitiser acquires its own bugs. The first version of this test asserted
    "evil.pdf" and was wrong about the mechanism, not about the safety.
    """
    hostile = resume_write.safe_filename('ev"il\r\nX-Injected: 1.pdf')
    for char in ('"', "\\", "\r", "\n", "\x00"):
        assert char not in hostile
    assert hostile.endswith(".pdf")

    assert resume_write.safe_filename("../../etc/passwd") == "passwd"
    assert resume_write.safe_filename("") == "resume"
    assert resume_write.safe_filename(None) == "resume"


# ===========================================================================
# 4. THE MULTIPART BODY - what actually goes on the wire
# ===========================================================================


async def test_the_body_is_exactly_two_parts_field_and_value(
    new_resume, isolated_snapshots
):
    """VERIFIED against the profile page's own handler: two appends, no more."""
    client, calls = client_over(routes())
    sender = resume_write.sender_for(client, endpoints.EP_PROFILE_UPSERT)

    await resume_write.replace_resume(
        client, str(new_resume()), confirm=True, send=sender
    )

    assert part_names(upserts(calls)[0]) == ["field", "value"]
    await client.aclose()


async def test_the_body_never_carries_tid(new_resume, isolated_snapshots):
    """`tid` is an impersonation parameter the profile page reads off the URL
    (`A.get("tid")`). Acting as himself it is absent; sending one would aim the
    write at somebody else's profile."""
    client, calls = client_over(routes())
    sender = resume_write.sender_for(client, endpoints.EP_PROFILE_UPSERT)

    await resume_write.replace_resume(
        client, str(new_resume()), confirm=True, send=sender
    )

    names = part_names(upserts(calls)[0])
    for forbidden in resume_write.NEVER_SENT:
        assert forbidden not in names
    await client.aclose()


async def test_the_field_part_says_resume_in_lowercase(new_resume, isolated_snapshots):
    """A grep of all 86 bundle files returns zero hits for an uppercase
    `RESUME_FILE_ID`; the literals are lowercase."""
    client, calls = client_over(routes())
    sender = resume_write.sender_for(client, endpoints.EP_PROFILE_UPSERT)

    await resume_write.replace_resume(
        client, str(new_resume()), confirm=True, send=sender
    )

    body = upserts(calls)[0].content
    assert b'name="field"' in body
    assert b"\r\n\r\nresume\r\n" in body
    assert b"RESUME" not in body
    await client.aclose()


async def test_the_value_part_carries_the_file_bytes_and_its_content_type(
    new_resume, isolated_snapshots
):
    """`value` is the raw File, VERIFIED: the onChange handler does
    `n=t.target.files[0]` then hands that object straight to the append."""
    client, calls = client_over(routes())
    sender = resume_write.sender_for(client, endpoints.EP_PROFILE_UPSERT)

    await resume_write.replace_resume(
        client, str(new_resume()), confirm=True, send=sender
    )

    body = upserts(calls)[0].content
    assert PDF_BYTES in body
    assert b'filename="Jane_Doe_New_Resume.pdf"' in body
    assert b"Content-Type: application/pdf" in body
    await client.aclose()


async def test_a_docx_gets_the_openxml_content_type(tmp_path, isolated_snapshots):
    client, calls = client_over(routes())
    path = tmp_path / "Jane_Doe_Resume.docx"
    path.write_bytes(DOCX_BYTES)
    sender = resume_write.sender_for(client, endpoints.EP_PROFILE_UPSERT)

    await resume_write.replace_resume(client, str(path), confirm=True, send=sender)

    body = upserts(calls)[0].content
    assert b"wordprocessingml.document" in body
    await client.aclose()


async def test_the_request_is_a_post_to_the_upsert_route_and_nothing_else(
    new_resume, isolated_snapshots
):
    """One write, one route. The three-call presigned-PUT path is deliberately
    not built, so a PUT to anything is a defect, not a variant."""
    client, calls = client_over(routes())
    sender = resume_write.sender_for(client, endpoints.EP_PROFILE_UPSERT)

    await resume_write.replace_resume(
        client, str(new_resume()), confirm=True, send=sender
    )

    assert [call.method for call in writes(calls)] == ["POST"]
    assert [call.url.path for call in writes(calls)] == [UPSERT_PATH]
    assert "generate-upload-url" not in " ".join(call.url.path for call in calls)
    await client.aclose()


def test_multipart_parts_refuses_a_type_uplers_does_not_take():
    with pytest.raises(WriteRefused):
        resume_write.multipart_parts("x.txt", b"data", "txt")


def test_multipart_parts_refuses_an_empty_body():
    with pytest.raises(WriteRefused):
        resume_write.multipart_parts("x.pdf", b"", "pdf")


# ===========================================================================
# 5. THE RESTORE - what makes any of this reversible
# ===========================================================================


async def test_restore_puts_the_original_bytes_back_byte_for_byte(
    new_resume, isolated_snapshots
):
    """THE round trip. Replace, then restore, and compare what went up.

    This is the assertion the whole design exists to make true: the bytes
    Uplers held before the replacement are the bytes the restore sends.
    """
    original = b"%PDF-1.4\nORIGINAL RESUME BODY\n%%EOF\n"
    client, calls = client_over(
        routes(download=download_body(data=original, filename="Jane_Doe_Old.pdf"))
    )
    sender = resume_write.sender_for(client, endpoints.EP_PROFILE_UPSERT)

    written = await resume_write.replace_resume(
        client, str(new_resume()), confirm=True, send=sender
    )
    snapshot_id = written["snapshot"]["snapshot_id"]
    assert PDF_BYTES in upserts(calls)[0].content        # the new file went up

    restored = await resume_write.restore_resume(
        client, snapshot_id, confirm=True, send=sender
    )

    assert restored["performed"] is True
    assert original in upserts(calls)[1].content         # the OLD file came back
    assert b'filename="Jane_Doe_Old.pdf"' in upserts(calls)[1].content
    assert restored["restoring"]["snapshot_id"] == snapshot_id
    await client.aclose()


async def test_restore_without_confirm_sends_nothing(new_resume, isolated_snapshots):
    """Same gate as the write it undoes. A restore IS a replacement write."""
    client, calls = client_over(routes())
    sender = resume_write.sender_for(client, endpoints.EP_PROFILE_UPSERT)
    await resume_write.replace_resume(
        client, str(new_resume()), confirm=True, send=sender
    )
    before = len(upserts(calls))

    recorder = Recorder()
    result = await resume_write.restore_resume(client, confirm=False, send=recorder)

    assert result["performed"] is False
    assert recorder.calls == []
    assert len(upserts(calls)) == before
    await client.aclose()


async def test_restore_snapshots_the_current_resume_before_replacing_it(
    new_resume, isolated_snapshots
):
    """A restore aimed at the wrong snapshot is the obvious way to lose work,
    so the state it overwrites is itself kept - the same `pre-restore` record
    `uplers_restore_profile` writes."""
    client, _ = client_over(routes())
    sender = resume_write.sender_for(client, endpoints.EP_PROFILE_UPSERT)
    await resume_write.replace_resume(
        client, str(new_resume()), confirm=True, send=sender
    )

    result = await resume_write.restore_resume(client, confirm=True, send=sender)

    assert result["snapshot"]["label"] == "pre-resume-restore"
    assert result["snapshot"]["written"] is True
    labels = [entry["label"] for entry in resume_write.list_snapshots()]
    assert "pre-resume-write" in labels
    assert "pre-resume-restore" in labels
    await client.aclose()


async def test_a_traversal_snapshot_id_is_refused(tmp_path, isolated_snapshots):
    """The guard the sibling Instahyre server did not have.

    There, `"../not-a-snapshot"` escaped the snapshots directory, resolved to a
    file with no skills in it, and the "restore" deleted all four of his.
    """
    outside = tmp_path / "not-a-snapshot.json"
    outside.write_text(json.dumps({"snapshot_id": "x", "blob_file": "x.pdf"}), encoding="utf-8")
    (isolated_snapshots / "1-real.json").write_text("{}", encoding="utf-8")
    client, calls = client_over(routes())

    with pytest.raises(WriteRefused) as caught:
        await resume_write.restore_resume(
            client, "../not-a-snapshot", confirm=True, send=Recorder()
        )

    assert "not a snapshot id" in str(caught.value)
    assert writes(calls) == []
    await client.aclose()


async def test_a_snapshot_naming_a_file_outside_the_directory_is_refused(
    isolated_snapshots, tmp_path
):
    """`blob_file` is read off a JSON file. This process wrote it, but cannot
    prove it wrote it, so it gets the same containment check the id got."""
    (tmp_path / "elsewhere.pdf").write_bytes(PDF_BYTES)
    (isolated_snapshots / "1755780000-escape.json").write_text(
        json.dumps(
            {
                "snapshot_id": "1755780000-escape",
                "blob_file": "../elsewhere.pdf",
                "ext": "pdf",
            }
        ),
        encoding="utf-8",
    )
    client, calls = client_over(routes())

    with pytest.raises(WriteRefused) as caught:
        await resume_write.restore_resume(
            client, "1755780000-escape", confirm=True, send=Recorder()
        )

    assert "not inside the" in str(caught.value)
    assert writes(calls) == []
    await client.aclose()


async def test_an_empty_snapshot_is_refused(isolated_snapshots):
    """Restoring nothing is not a no-op here: it is an instruction to replace
    the resume recruiters see with an empty file."""
    (isolated_snapshots / "1755780000-empty.pdf").write_bytes(b"")
    (isolated_snapshots / "1755780000-empty.json").write_text(
        json.dumps(
            {
                "snapshot_id": "1755780000-empty",
                "blob_file": "1755780000-empty.pdf",
                "ext": "pdf",
            }
        ),
        encoding="utf-8",
    )
    client, calls = client_over(routes())

    with pytest.raises(WriteRefused) as caught:
        await resume_write.restore_resume(
            client, "1755780000-empty", confirm=True, send=Recorder()
        )

    assert "zero bytes" in str(caught.value)
    assert writes(calls) == []
    await client.aclose()


async def test_a_snapshot_that_does_not_match_its_checksum_is_refused(
    new_resume, isolated_snapshots
):
    """A file edited under the record is not the file that was saved, and this
    tool would be uploading it to his live profile."""
    client, calls = client_over(routes())
    sender = resume_write.sender_for(client, endpoints.EP_PROFILE_UPSERT)
    written = await resume_write.replace_resume(
        client, str(new_resume()), confirm=True, send=sender
    )
    snapshot_id = written["snapshot"]["snapshot_id"]
    (isolated_snapshots / ("%s.pdf" % snapshot_id)).write_bytes(b"%PDF-1.4 TAMPERED")
    before = len(upserts(calls))

    with pytest.raises(WriteRefused) as caught:
        await resume_write.restore_resume(
            client, snapshot_id, confirm=True, send=sender
        )

    assert "checksum" in str(caught.value)
    assert len(upserts(calls)) == before
    await client.aclose()


async def test_restoring_with_no_snapshots_at_all_refuses(isolated_snapshots):
    client, calls = client_over(routes())

    with pytest.raises(WriteRefused) as caught:
        await resume_write.restore_resume(client, confirm=True, send=Recorder())

    assert "no resume snapshot to restore from" in str(caught.value)
    assert writes(calls) == []
    await client.aclose()


# ===========================================================================
# 6. THE RESULT A READER GETS BACK
# ===========================================================================


async def test_the_result_hands_back_a_usable_undo_handle(
    new_resume, isolated_snapshots
):
    """`profile_write` returns its backup path as the undo handle. So does
    this, and it also returns the exact call that uses it."""
    client, _ = client_over(routes())
    sender = resume_write.sender_for(client, endpoints.EP_PROFILE_UPSERT)

    result = await resume_write.replace_resume(
        client, str(new_resume()), confirm=True, send=sender
    )

    assert result["snapshot"]["written"] is True
    assert result["snapshot"]["path"].endswith(".pdf")
    assert "uplers_restore_resume(" in result["undo"]
    assert result["snapshot"]["snapshot_id"] in result["undo"]
    await client.aclose()


async def test_no_result_leaks_this_machines_absolute_layout(
    new_resume, isolated_snapshots
):
    """Every path leaves through policy.display_path. A drive letter in a tool
    response publishes the box's directory layout into any shared transcript."""
    client, _ = client_over(routes())
    sender = resume_write.sender_for(client, endpoints.EP_PROFILE_UPSERT)

    preview = await resume_write.replace_resume(
        client, str(new_resume()), confirm=False, send=sender
    )
    performed = await resume_write.replace_resume(
        client, str(new_resume()), confirm=True, send=sender
    )

    for result in (preview, performed):
        blob = json.dumps(result)
        assert not re.search(r"[A-Za-z]:[\\/]{1,2}", blob), blob[:400]
    await client.aclose()


async def test_the_snapshot_record_can_be_listed_and_carries_its_checksum(
    new_resume, isolated_snapshots
):
    client, _ = client_over(routes())
    sender = resume_write.sender_for(client, endpoints.EP_PROFILE_UPSERT)
    await resume_write.replace_resume(
        client, str(new_resume()), confirm=True, send=sender
    )

    entries = resume_write.list_snapshots()

    assert len(entries) == 1
    assert entries[0]["filename"] == "Jane_Doe_Resume.pdf"
    assert entries[0]["bytes"] == len(PDF_BYTES)
    assert entries[0]["restorable"] is True
    assert entries[0]["taken_at_iso"].endswith("+00:00")
    await client.aclose()


def test_listing_survives_one_unreadable_record(isolated_snapshots):
    """An operator hunting for a restore point after a bad write is the worst
    possible moment for the list to raise."""
    (isolated_snapshots / "1755780000-good.json").write_text(
        json.dumps({"snapshot_id": "1755780000-good", "bytes": 10}), encoding="utf-8"
    )
    (isolated_snapshots / "1755780001-broken.json").write_text(
        "{not json", encoding="utf-8"
    )

    entries = resume_write.list_snapshots()

    assert [entry["snapshot_id"] for entry in entries] == ["1755780000-good"]
