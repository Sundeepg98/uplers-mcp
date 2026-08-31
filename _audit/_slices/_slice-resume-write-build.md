# Uplers resume replacement - BUILT, READY, NEVER FIRED

Date: 2026-08-24
Slice: build the resume-replacement capability. Two new files, no edits to any
existing file, and **not one request sent to Uplers**.

Shape source: `_audit/_slices/_slice-resume-write-shape.md`, read in full and
verified claim by claim rather than taken from the brief.

---

## 0. The absolute constraint, and how it is evidenced

**Zero writes were fired against Uplers. Zero requests of any kind were made to
platform.uplers.com during this slice.** The evidence, in the order it can be
checked:

| check | result |
|---|---|
| Any `mcp__uplers__*` tool called | none, at any point in the slice |
| Resume tools wired into `server.py` | `grep -c "uplers_replace_resume\|uplers_restore_resume\|resume_write" server.py` -> **0**. The capability is not reachable from the running server until the lead wires it. |
| Every test's transport | `httpx.MockTransport`, per the suite's first standing invariant. No test constructs a networked client. |
| The wiring proof harness | also `MockTransport`; it never touched `_session_store()` and used a synthetic token string. |
| `data/` after the slice | unchanged - no `resume_snapshots/` directory exists there; every snapshot in every test went to `tmp_path` via an **autouse** fixture. |

The module is additionally **structurally unable to send on its own**: the two
orchestrators take a `send` callable and refuse when they do not have one. See
section 2.

---

## 1. Files written

| path | lines | what |
|---|---|---|
| `D:\workspace\projects\job-hunting\mcp-servers\uplers\uplers_server\resume_write.py` | 990 | validation, snapshot, restore, multipart builder, and the two orchestrators |
| `D:\workspace\projects\job-hunting\mcp-servers\uplers\tests\test_resume_write.py` | 1009 (40 tests) | mocks and synthetic fixtures only |

Both files are strict ASCII (measured: 0 bytes > 127 in either). No existing
file was edited. Nothing was staged; nothing was committed.

---

## 2. Design

### 2.1 Which path was built

**Sequence A only** - the single multipart call the profile page itself uses:

```
POST talent/profile-upsert       multipart/form-data
     field=resume
     value=<the file bytes>
```

Verified against the slice's quoted call site (`196.6de42d0ddab10b51.js`
@104539). The three-call `generate-upload-url` -> presigned PUT ->
`field=resume_file_id` path is **not built** and the module refuses to build
any part named `resume_file_id`, `transformation_file_id` or `tid`
(`resume_write.NEVER_SENT`). No third-party storage endpoint is touched.

### 2.2 The rollback, which is the reason this is buildable

`GET talent/talent-download-resume-profile?talent_id=<talent_enc_id>` returns
`{blob: <base64>, ext, filename}` - the real bytes. It takes one parameter and
no version, so it always returns THE CURRENT resume. That is why the snapshot
must be pre-flight and why post-hoc recovery does not exist.

`talent_enc_id` is read from `talent_details.enc_id` on the profile response -
**measured in the committed `tests/fixtures/talent_profile.json`**, not assumed.

### 2.3 Where the orchestration lives, and why

The sibling `profile_write.py` states "nothing here performs a request" and
keeps its two write tools' bodies in `server.py`. This module deviates in one
respect and matches in the one that matters:

* **It matches on the safety property.** `resume_write.py` never names the
  upsert route constant and cannot reach it. It is HANDED a `send` callable
  built by `server.py`, and `_require_sender` refuses when it has none. So the
  write still cannot fire as a side effect of anything, and
  `test_the_upsert_route_is_reachable_from_the_write_tools_and_nowhere_else`
  (which scans every `uplers_server/*.py` for `EP_PROFILE_UPSERT` and demands
  every hit be in `server.py`) stays meaningful and still passes.
* **It deviates on where the steps live.** The ordered logic - validate,
  snapshot, verify, only then send - is in `resume_write.py` rather than in
  `server.py`, because this slice may not edit `server.py` and **a test that
  exercises a COPY of the tool proves nothing about the tool.** The guards
  under test are the ones that will run in production; `server.py`'s wrappers
  are three lines each and contain no logic to get wrong.

The two reads (`EP_PROFILE`, `EP_DOWNLOAD_RESUME`) do happen inside the module.
They are reads, and `EP_PROFILE` is used through `client.get_json`, which is
what `test_the_plain_profile_route_is_only_ever_read` requires.

### 2.4 The seam, and the one wart in it

`TalentClient` has **no public verb for a multipart body carrying file bytes**.
`post_form` is multipart but renders every value as `(None, str(value))` -
correct for the apply route's scalar fields, and destructive here, since
`str(b"%PDF...")` is a repr rather than the file. So `resume_write.sender_for`
reaches for `client._request` directly.

**The clean home for this is a `post_multipart` verb on `TalentClient`**, and
`sender_for` should become a two-line call to it. That edit is `talent.py`,
which this slice may not touch. The wart is confined to one commented function.

---

## 3. The guard list

Every guard, what it refuses, and the test that pins it. All 40 tests pass.

### Preconditions on the file going up - each costs ZERO requests

| # | guard | refusal | test |
|---|---|---|---|
| 1 | file must be named | "No file was named." | (covered by 4) |
| 2 | file must exist | "There is no file at ..." | `test_a_missing_file_is_refused_and_costs_zero_requests` |
| 3 | must be a file, not a directory | "... is not a file." | `test_a_directory_is_refused` |
| 4 | extension in {pdf, docx} | quotes Uplers verbatim: "The resume must be a file of type: pdf, docx." | `test_a_txt_file_is_refused_and_costs_zero_requests` |
| 5 | non-empty | quotes Uplers: "Please add your resume" | `test_an_empty_file_is_refused_and_costs_zero_requests` |
| 6 | <= 2 MB | quotes Uplers and their arithmetic `size/1024 > 2048` | `test_a_file_over_two_megabytes_is_refused_and_costs_zero_requests` |
| 7 | the boundary is theirs, to the byte | 2097152 is ACCEPTED, because their gate rejects only above it | `test_a_file_of_exactly_two_megabytes_is_accepted` |

These run **before any network call**, so tests 2/4/5/6 assert `calls == []` -
not merely "no writes", but no requests at all.

### The snapshot precondition - no snapshot means no write

| # | guard | refusal | test |
|---|---|---|---|
| 8 | profile must carry `talent_details.enc_id` | the download route's only parameter is missing, so no snapshot is possible | `test_a_profile_with_no_enc_id_stops_the_write` |
| 9 | download must carry a `blob` | "no copy of your current resume to keep" | `test_a_download_with_no_blob_stops_the_write` |
| 10 | `blob` must be decodable base64 | the copy would not be the file | (guard present; no separate test - see section 7) |
| 11 | it must decode to > 0 bytes | "either there is no resume yet, or the read failed - and this server cannot tell those apart" | `test_a_download_that_decodes_to_zero_bytes_stops_the_write` |
| 12 | the bytes must reach disk | catches `OSError`: full disk, read-only dir, permissions | `test_a_snapshot_that_cannot_reach_the_disk_stops_the_write` |
| 13 | the bytes must **read back identical** | a file that exists and is WRONG is what a bare `.exists()` misses | `test_a_snapshot_that_reads_back_wrong_stops_the_write` |
| 14 | the sidecar record must be writable | bytes with nothing able to find them again is not a restore point | (guard present) |
| 15 | the snapshot must be **restorable** | bytes are KEPT, write is REFUSED - see below | `test_an_unrestorable_snapshot_is_kept_but_the_write_is_refused` |
| 16 | ORDER: snapshot on disk before the request leaves | asserted from inside the transport, at the only moment the question has an answer | `test_the_snapshot_is_on_disk_BEFORE_the_request_leaves` |

**Guard 15 is the one deliberate non-binary.** If the current resume comes back
as, say, a `.doc`, its bytes are still the only copy in existence, so they are
saved - and the write is then refused, because a copy that cannot be
re-uploaded is not a rollback. Throwing the bytes away to make the guard
uniform would destroy the thing the guard exists to protect.

### The confirm gate

| # | guard | test |
|---|---|---|
| 17 | `confirm=False` sends nothing - asserted at the seam, at the transport, and at the route | `test_without_confirm_nothing_is_sent_and_the_sender_is_never_called` |
| 18 | `confirm=False` writes no snapshot either | `test_without_confirm_no_snapshot_is_written_either` |
| 19 | `confirm=True` with no sender refuses BEFORE snapshotting | `test_a_confirmed_write_with_no_sender_refuses_before_snapshotting` |

Guard 19's ordering is deliberate: a call that could never have sent anything
must not leave a restore point behind for a write that was never going to
happen.

### The wire body

| # | guard | test |
|---|---|---|
| 20 | exactly two parts, `field` then `value`, in the bundle's order | `test_the_body_is_exactly_two_parts_field_and_value` |
| 21 | **no `tid`** - and none of `NEVER_SENT` | `test_the_body_never_carries_tid` |
| 22 | `field` is lowercase `resume`; no uppercase spelling anywhere in the body | `test_the_field_part_says_resume_in_lowercase` |
| 23 | `value` carries the real bytes, a filename and a content type | `test_the_value_part_carries_the_file_bytes_and_its_content_type` |
| 24 | docx gets the openxml content type | `test_a_docx_gets_the_openxml_content_type` |
| 25 | exactly one POST, to the upsert route, and no `generate-upload-url` anywhere | `test_the_request_is_a_post_to_the_upsert_route_and_nothing_else` |
| 26 | a filename cannot break the Content-Disposition header | `test_a_filename_cannot_break_the_multipart_header` |

### The restore

| # | guard | test |
|---|---|---|
| 27 | round trip: the bytes Uplers held come back byte-for-byte | `test_restore_puts_the_original_bytes_back_byte_for_byte` |
| 28 | same confirm gate as the write it undoes | `test_restore_without_confirm_sends_nothing` |
| 29 | snapshots the CURRENT resume first (`pre-resume-restore`) | `test_restore_snapshots_the_current_resume_before_replacing_it` |
| 30 | snapshot id must look like an id - validated BEFORE the directory is listed | `test_a_traversal_snapshot_id_is_refused` |
| 31 | the resolved path must stay inside the snapshots directory | (behind 30, per the sibling's design) |
| 32 | `blob_file` from the record gets the SAME containment check | `test_a_snapshot_naming_a_file_outside_the_directory_is_refused` |
| 33 | a zero-byte snapshot is refused - restoring it is not a no-op, it is a delete | `test_an_empty_snapshot_is_refused` |
| 34 | sha256 must match the record | `test_a_snapshot_that_does_not_match_its_checksum_is_refused` |
| 35 | ext and size are re-checked at restore time | (guards present) |
| 36 | no snapshots at all -> refuse, do not improvise | `test_restoring_with_no_snapshots_at_all_refuses` |

Guards 30-33 are the Instahyre scars, copied deliberately: there, a
`snapshot_id` of `"../not-a-snapshot"` escaped the directory and the "restore"
destroyed real data.

### Honesty, enforced by test

| # | guard | test |
|---|---|---|
| 37 | the preview says "recruiters", "NO previous copy", "ONLY way back", "UNRESOLVED", "not the RECORD" | `test_the_preview_says_plainly_what_this_costs` |
| 38 | the preview must NOT soft-pedal - "is safe", "is contained", "no side effects", "harmless" are forbidden strings, and "absence of evidence" must be present | `test_the_preview_does_not_call_the_blast_radius_safe` |
| 39 | no result leaks this machine's absolute layout | `test_no_result_leaks_this_machines_absolute_layout` |

Guard 38 is a negative assertion on purpose. "Nothing in the bundle names such
an effect" is true and is not "safe"; a future rewrite that trades the second
sentence for the first will fail this test.

---

## 4. Planted-control evidence

Every test in this file was run and seen passing. For the guards that carry the
safety, the guard itself was **deliberately broken**, the test watched go red,
the file restored from a byte-for-byte backup (sha256 verified identical), and
the test watched go green again.

Harness: `plant_controls.py` in this session's scratchpad. Pristine sha256 of
`resume_write.py`: `8b1cc630efaab9baa296c10468a7bd3a36f433e2e31330d5c5a5e2596287b036`,
identical after every restore.

### CONTROL A - the confirm gate

Defect: `if not confirm:` in `replace_resume` changed to `if False:`.

```
>       assert sender.calls == []
E       AssertionError: assert [{'field': (N...cation/pdf')}] == []
E         Left contains one more item: {'field': (None, 'resume'), 'value':
E         ('Jane_Doe_New_Resume.pdf', b'%PDF-1.4\n1 0 obj<</Type/Catalog>>endobj\n%%EOF\n',
E         'application/pdf')}
>       assert snapshot_files(isolated_snapshots) == []
E       AssertionError: assert ['1787510404-...me-write.pdf'] == []
FAILED tests/test_resume_write.py::test_without_confirm_nothing_is_sent_and_the_sender_is_never_called
FAILED tests/test_resume_write.py::test_without_confirm_no_snapshot_is_written_either
2 failed, 38 passed
```

The red output prints **the exact multipart body that would have gone to his
live profile**. That is the control working: the failure names the damage.

**This control changed the test.** Its first run reported only
`assert True is False`, because `assert result["performed"] is False` was
written first and short-circuited the run before the claim anyone cares about
was reached. The assertions were reordered so the "did a REQUEST happen"
claims report first. A control that only proves a flag is wrong is a weaker
control than one that proves a request was made.

### CONTROL B - the snapshot precondition

Defect: the `write_snapshot` call wrapped in `try/except WriteRefused` with a
stub snapshot substituted - i.e. the realistic regression, "make the snapshot
best-effort so the tool fails less often".

```
>       with pytest.raises(WriteRefused) as caught:
E       Failed: DID NOT RAISE WriteRefused
>       with pytest.raises(WriteRefused) as caught:
E       Failed: DID NOT RAISE WriteRefused
FAILED tests/test_resume_write.py::test_a_snapshot_that_cannot_reach_the_disk_stops_the_write
FAILED tests/test_resume_write.py::test_a_snapshot_that_reads_back_wrong_stops_the_write
2 failed, 38 passed
```

### CONTROL C - the snapshot is OBTAINABLE

Defect: the missing-`blob` guard in `decode_download` removed.

```
>           raise TypeError("argument should be a bytes-like object or ASCII "
E           TypeError: argument should be a bytes-like object or ASCII string, not 'NoneType'
FAILED tests/test_resume_write.py::test_a_download_with_no_blob_stops_the_write
1 failed, 39 passed
```

**Read this one honestly.** With the guard removed, the write is still stopped
- but by a `TypeError` from `base64.b64decode(None)`, not by a decision. So
what that guard buys is a **legible refusal that names the consequence**, not
the prevention of a write. The test does fail without it, so it is a real
control, but the claim it supports is the narrower one.

### Restore verified

```
RESTORED - expecting GREEN
40 passed in 0.91s
restored sha256: 8b1cc630...87b036 == pristine: True
```

---

## 5. A real bug the tests found in my own code

`test_no_result_leaks_this_machines_absolute_layout` failed on its first run:

```
E   AssertionError: ... "to_confirm": "uplers_replace_resume('C:\\\\Users\\\\...
E   assert not <re.Match object; match='C:\\\\'>
```

`result["to_confirm"]` was echoing the caller's raw absolute `file_path` back
into the tool response - publishing the box's directory layout into any shared
transcript. Fixed to use `upload["path"]`, which has already been through
`policy.display_path`. This is the second time in this server that an
undo/confirm handle has been the path-leak site; the fix carries a comment
saying so.

Three test defects were also found and fixed on the first run, each recorded in
the test that carried it: a `name="..."` regex that also matched
`filename="..."`; a `Path.write_bytes` monkeypatch that killed the fixture
creating the upload (the test would have passed for the wrong reason); and an
expectation that `safe_filename` would reconstruct `"evil.pdf"` from an
injection payload, replaced by an assertion on the actual safety property.

---

## 6. The code to wire

### 6.1 Import edit

In `server.py`, add `resume_write` to the existing `from uplers_server import (...)`
block, alphabetically after `profile_write` (line ~50):

```python
    profile_write,
    resume_write,
```

### 6.2 The tools

**This block was proven verbatim.** It was compiled and exec'd into the live
`server` module's own namespace with `resume_write` bound exactly as the import
edit binds it, then driven end to end over a `MockTransport`. Measured result:

```
tools before wiring: 50  after: 53
PREVIEW  performed: False  writes so far: 0
PREVIEW  parts: {'field': 'resume', 'value': "<26 bytes, filename 'Jane_Doe_New.pdf', application/pdf>"}
PREVIEW  snapshots on disk: []
CONFIRM  performed: True  writes: 1
CONFIRM  part names: ['field', 'value']
CONFIRM  new bytes on wire: True  tid absent: True
CONFIRM  undo handle: uplers_restore_resume(snapshot_id='...-pre-resume-write', confirm=True)
LIST     count: 1  directory: ~/AppData/Local/Temp/resume-snap-...
RESTORE  performed: True  old bytes back on wire: True
```

No file was edited to obtain that.

```python
# --------------------------------------------------------------- tool 51 ---
#
# The resume write. Read `uplers_server/resume_write.py` before touching any of
# the three tools below. Uplers keeps NO previous copy of a resume - VERIFIED
# absences across their whole production bundle, and their download route takes
# no "which resume" parameter - so the pre-flight snapshot is not a convenience,
# it is the entire rollback story. Everything in that module is a guard around
# taking it BEFORE the write, or around the restore being turned into a delete.


@mcp.tool()
async def uplers_replace_resume(file_path: str, confirm: bool = False) -> dict:
    """Replace the resume Uplers recruiters see. Previews by default.

    This changes who you are on Uplers rather than acting on a job, and it is
    the only write here that acts on a FILE. Whether it SHOULD run is not this
    server's call.

    READ THIS BEFORE CONFIRMING. Uplers keeps no previous copy: no history, no
    version list, no archive, and no revert route anywhere in their product.
    The only rollback that exists is the snapshot this tool takes BEFORE the
    write - their own download route has no "which resume" parameter, so once
    the replacement lands it returns the new file and the old one is
    unreachable. If the snapshot cannot be taken, or cannot be written to disk,
    or comes back in a form that cannot be re-uploaded, THE WRITE DOES NOT
    HAPPEN. That is a precondition, not a warning.

    The snapshot restores the FILE, not the RECORD. Anything Uplers derived
    from the old resume - parsed profile fields, a health score, a tailored
    variant - is not put back by re-uploading bytes.

    And the blast radius is UNRESOLVED. The bundle names a profile-completion
    recompute and nothing else, but whether Uplers re-parses, re-scores,
    notifies a recruiter or touches already-submitted applications could not be
    determined from a client bundle, and absence of evidence there is not
    evidence of absence on their server. Do not read this write as contained.

    With confirm=False it returns the exact request it would send, tells you
    whether a restore point can be taken, and changes nothing.

    Args:
        file_path: the new resume. pdf or docx, 2 MB maximum - Uplers' own
            gate, mirrored to the byte.
        confirm: False previews. True snapshots, then sends.
    """
    async with _talent_client() as client:
        return await resume_write.replace_resume(
            client,
            file_path,
            confirm=confirm,
            send=resume_write.sender_for(client, endpoints.EP_PROFILE_UPSERT),
        )


@mcp.tool()
async def uplers_restore_resume(
    snapshot_id: str | None = None, confirm: bool = False
) -> dict:
    """Put a snapshotted resume back on your profile. Previews by default.

    Snapshots are written automatically before every uplers_replace_resume()
    write. This uploads one of them again.

    It is a fresh upload through the same replacement route, not a revert, so
    it is exactly as destructive as the thing it undoes: whatever is on the
    profile now is replaced by what the snapshot holds. That state is itself
    snapshotted first. Preview before confirming.

    Args:
        snapshot_id: which restore point. Omit for the most recent.
        confirm: False previews. True sends the write.
    """
    async with _talent_client() as client:
        return await resume_write.restore_resume(
            client,
            snapshot_id,
            confirm=confirm,
            send=resume_write.sender_for(client, endpoints.EP_PROFILE_UPSERT),
        )


@mcp.tool()
async def uplers_list_resume_snapshots() -> dict:
    """Resume restore points, newest first. Reads disk only, needs no session.

    One is written before every uplers_replace_resume() write and one before
    every restore. Each entry names the file, its size and its sha256, and says
    whether it can be re-uploaded. An empty list means this server has never
    replaced your Uplers resume.
    """
    entries = resume_write.list_snapshots()
    return {
        "snapshots": entries,
        "directory": policy_mod.display_path(str(resume_write.snapshots_dir())),
        "notes": (
            []
            if entries
            else [
                "No resume snapshots. This server has never replaced your Uplers "
                "resume."
            ]
        ),
    }
```

### 6.3 What wiring will break, and how to fix it

`tests/test_tools.py::test_importing_server_registers_exactly_the_expected_tools`
asserts an exact tool count and an exact `TOOL_NAMES` set. Wiring these three
takes the live count from **50 to 53**, so that test's number and its
`TOOL_NAMES` set both need updating, plus whatever write-set membership
assertions live beside them - note that file already asserts that certain
tool-name sets do not intersect the write sets, and `uplers_replace_resume` and
`uplers_restore_resume` are **writes** and belong in a write set, while
`uplers_list_resume_snapshots` is a pure disk read.

That test is **already failing before these three tools exist** - see section 7.

---

## 7. Test results

Baseline taken at the start of this slice, before writing anything:

```
1251 passed in 43.44s
```

After adding my two files, on the first full run:

```
1 failed, 1342 passed in 47.99s
```

and on the final run twenty minutes later, with no further change from me:

```
1343 passed in 57.69s
```

* **My file: 40 tests, 40 passing.** `pytest tests/test_resume_write.py -q` ->
  `40 passed`.
* The suite grew by 92 tests between my baseline and now. 40 are mine; the rest
  are other agents landing work concurrently.

### The one failure was not mine, I did not fix it, and its owner has since fixed it

Recorded because it happened and because the fix has a consequence for the
wiring in section 6.3. At the time of my first full run:

```
tests/test_tools.py::test_importing_server_registers_exactly_the_expected_tools
>       assert len(tools_listed) == 47
E       AssertionError: assert 50 == 47
```

Evidence that it is not from this slice:

* `grep -c "uplers_replace_resume\|uplers_restore_resume\|resume_write" server.py`
  -> **0**. None of my work is reachable from `server.py`.
* `git diff --stat -- server.py` -> **149 insertions**, none of them mine.
* Diffing the live tool list against `git show HEAD:server.py` names the three
  new tools: **`uplers_agent_settings`, `uplers_email_scan`,
  `uplers_scanned_jobs`**, alongside a new untracked
  `uplers_server/agent_surface.py` and `tests/test_agent_surface.py`.
* `tests/test_tools.py` is NOT in `git status`'s modified list, so its expected
  count of 47 was never updated for those three.

So: whichever agent built `agent_surface.py` wired three tools without updating
the tool-count assertion. I reported it rather than fixing it - not my file.

**It has since been fixed by its owner**, mid-slice and without any action from
me: `git diff -- tests/test_tools.py` now shows `47 -> 50` and
`AGENT_READ_TOOL_NAMES 4 -> 7`, and the full suite is green at 1343 passed.

The consequence for section 6.3 is unchanged and now sharper: that assertion is
pinned at **50**, so wiring these three tools breaks it again at **53**. It
needs updating in the same commit that wires them, together with `TOOL_NAMES`,
and `uplers_replace_resume` / `uplers_restore_resume` need adding to a write
set (`uplers_list_resume_snapshots` is a pure disk read and must NOT go in one).

---

## 8. Decisions and open items for the lead

1. **This tool cannot do a FIRST upload, only a REPLACE.** The brief made an
   empty snapshot a hard block ("if the snapshot fails, is empty, or cannot be
   written to disk, the write does not happen"), and an account with no resume
   yet returns an empty blob. That is implemented as briefed. Consequence is
   stated here rather than quietly worked around - if a first-upload path is
   ever wanted it is a separate tool with a different, explicitly stated
   safety story, because it genuinely has nothing to lose.

2. **`EP_DOWNLOAD_RESUME` belongs in `endpoints.py`.** It lives in
   `resume_write.py` only because this slice edits no existing file. Moving it
   is one line plus its comment block.

3. **`TalentClient` wants a `post_multipart` verb.** Then `sender_for` stops
   using `client._request`. See section 2.4.

4. **These tools return `dict`, not a Pydantic model.** Precedent exists
   (`uplers_agent_readthrough() -> dict`), but a `ResumeWriteResult` in
   `talent_models.py` would be better - `talent_models.py` was off-limits here.

5. **The shape slice's own open question is still open**, and it is the one
   thing that could turn "snapshot or nothing" into something softer: whether
   `resume_list` ever returns more than one `list_type=="profile"` entry. One
   authenticated READ of the tailor dashboard settles it. It was not probed
   here - the brief scoped this slice to a build, and no live call of any kind
   was made.

6. **Snapshots are his actual resume on this disk.** `profile_write` explicitly
   refuses to persist personal data because it buys nothing there; here it buys
   the only rollback that exists, so the trade goes the other way. `data/` is
   gitignored, and the snapshot directory is `data/resume_snapshots/` -
   deliberately NOT inside `data/profile_snapshots/`, which
   `uplers_list_profile_snapshots` globs and `profile_write.load_snapshot`
   would refuse resume records from.

7. **The blast radius is still UNRESOLVED and the code says so in four places**
   (module docstring, `BLAST_RADIUS_UNRESOLVED`, every preview's notes, and the
   tool docstring). Guard 38 is a test that fails if a future edit softens it.
