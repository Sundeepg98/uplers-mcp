# Uplers resume WRITE SHAPE - static bundle analysis

Date: 2026-08-23
Scope: static analysis of PUBLIC, UNAUTHENTICATED static assets only.
No login. No POST. No authenticated request. No `mcp__uplers__*` tool call.
Only HTTP GET on `https://platform.uplers.com/build/...`.

Every claim tagged VERIFIED (quoting bundle source, naming file+offset) /
INFERRED (reading intent) / UNRESOLVED (the bundle cannot settle it).

---

## 0. Corpus and provenance

| file | bytes | sha256 |
|---|---|---|
| `app.js` | 7,935,093 | `97052b350d6f664918342ab17c08f2d904a3ffe606d38fa702a1a5b9fab10eed` |
| 85 lazy chunks | 5,476,711 total | (per-chunk hashes = the filenames) |

Saved at `D:\claude-workspace\uplers-bundle-2\` (86 files, all HTTP 200, zero
fetch failures). A sibling agent was mid-download into
`D:\claude-workspace\uplers-bundle\` (6 files at poll time); that directory was
NOT touched.

VERIFIED: this corpus is byte-identical to the one the 2026-08-22 exhaustive
route inventory measured - same `app.js` size AND same sha256, and the 85-chunk
byte total matches to the byte. **The analysis below is not measuring a
different build from the prior audits.**

### Premise check (brief said 3 x RESUME + 2 x RESUME_FILE_ID)

VERIFIED and CONFIRMED, with one naming correction: the literals in the bundle
are **lowercase** - `"resume"` and `"resume_file_id"`. There is no uppercase
`RESUME_FILE_ID` token anywhere in the corpus (grep: 0 hits). Enumerating every
call of the profile-upsert dispatcher gives **19 call sites**, of which exactly
**3 carry `field="resume"`** and exactly **2 carry `field="resume_file_id"`**.
Counts match the brief exactly.

### Symbol map (VERIFIED, needed to read the quotes below)

| minified | meaning |
|---|---|
| `Imf` | route const `talent/profile-upsert` (`E=o+"talent/profile-upsert"`) |
| `P7` | the single redux dispatcher that POSTs to it (`je`) |
| `FeL` / `rA` | route + dispatcher for `talent/generate-upload-url` |
| `f5v` / `fN` | route + dispatcher for `talent/talent-download-resume-profile` |
| `JkU` / `_x` | route + dispatcher for `talent/resume-health-check/update-resume-in-profile` |
| `qpI` | route const `talent/profile/delete-details` |
| `NA` | recursive FormData bracket-flattener |
| `lq` | refetch of `user/me` |

There is exactly ONE function in the whole bundle that POSTs to
`talent/profile-upsert`. VERIFIED, `app.js`:

```js
je=function(e){var t=arguments.length>1&&void 0!==arguments[1]&&arguments[1];
 return function(n){return new Promise(function(r,s){
  t||n({type:a.rQ,payload:!0}),
  (0,i.o$)(o.Imf,e).then(function(e){r(e),
    e.data.profile_completion_percentage&&(
      n({type:a.XO,payload:e.data.profile_completion_percentage}),
      n({type:a.iC,payload:e.data.profile_remaining_percentage}))})
```

So the body `e` is passed through VERBATIM - the dispatcher imposes no shape.
Arg 2 (`t`) is only a spinner-suppression flag, not a wire field.

---

## 1. The 5 call sites

### Encoding: JSON vs multipart

VERIFIED, and this is a correction worth stating plainly: **every one of the 5
resume call sites is `multipart/form-data`, not JSON.** All five build a
`FormData` before calling `P7`. (The already-built `skills` path sends a plain
object, which axios serializes as JSON - the resume paths do not.)

### R1 + R3 - `field="resume"`, value = a raw File (Resume Health Check nudge)

R1 = `1248.793b7d5f36271fde.js` @216237; R3 = `2764.30e7f8791dfc6980.js` @322274.
The two are the same component shipped in two chunks (a modal and a
"replaceNudge" variant). VERIFIED, byte-identical call bodies:

```js
var e=new FormData;
e.append("field","resume"),
e.append("value",E),
e.append("transformation_file_id",s.transform.file_id),
(0,c.P7)(e)(S).then(function(e){a(!0),(0,c.lq)(!1)(S),
  p.oR.success("Resume updated successfully in your profile",{duration:7e3}),
  S({type:f.u3,payload:{resume:e.data.data}}),(0,x.y6)(null==E?void 0:E.name)})
```

- `value` = `E` = **the raw `File` object**, VERIFIED: the onChange handler does
  `n=t.target.files[0]` then `P(n)`, so `E` holds the File itself, never an id
  or filename.
- Carries an EXTRA part `transformation_file_id` and **no `tid`**.
- Screen: the Resume Health Check post-transform modal - headline
  *"Hey there! Looks like you just gave your resume a makeover with us"*, input
  `id="resumeUploadReplace"`, button *"update new resume in profile"*.

### R2 - `field="resume"`, value = a raw File (THE PROFILE PAGE)

`196.6de42d0ddab10b51.js` @104539. This is the one that matters for the
operator's use case. VERIFIED:

```js
var e,t,n=new FormData;
n.append("field","resume"),
n.append("value",N),
m&&n.append("tid",m),
(0,c.P7)(n)(A).then(function(e){
  A({type:d.u3,payload:{resume:e.data.data}}),T()})
```

- `value` = `N` = **the raw `File`**. `tid` appended only if present.
- No `transformation_file_id`.
- Screen: profile edit, section heading **"Your Resume"**, input
  `id="resumeReplace"`, label *"UPLOAD NEW FILE"* (or *"ADD YOUR RESUME"* when
  empty), hint *"PDF, DOCX | Max: 2 MB"*.
- **This is a ONE-CALL path. No separate upload route is involved.**
- Response: `e.data.data` is a **filename string** - INFERRED but strongly, from
  how it is consumed everywhere: `w.resume.split(".").pop().toLowerCase()` to
  choose a pdf/docx icon, and rendered directly as the display title.

### RFI1 - `field="resume_file_id"` (resume-editor / tailor, transformed PDF)

`2764.30e7f8791dfc6980.js` @255734. VERIFIED:

```js
var r,i={},o={resume_file_id:n.data.data.file_id};
i.field="resume_file_id",i.value=o;
for(var a=new FormData,s=0,l=Object.entries(i);s<l.length;s++){
  var c=Qt(l[s],2),u=c[0],p=c[1];a=(0,j.NA)(a,p,u)}
(0,w.P7)(a,!0)(e).then(function(t){
  e({type:d.u3,payload:Jt({},t.data.data)}),
  sessionStorage.setItem("fetchLatestResume",!0),
  g.Ay.success("Resume uploaded to profile successfully",{duration:6e3}),
  e({type:d.rQ,payload:!1}),(0,w.lq)(!1)(e)})
```

- `value` is an **OBJECT** `{resume_file_id: <id>}`, not a bare id.

### RFI2 - `field="resume_file_id"` (profile preferences page / modal)

`app.js` @1696553. VERIFIED:

```js
pn=function(){... if(!nn.current){e.n=2;break} return e.n=1,nn.current;
 case 1:o=e.v;
 case 2: for(o&&(n.resume_file_id=o),r.field="resume_file_id",r.value=n,
   i=new FormData,a=0,s=Object.entries(r);a<s.length;a++)
     l=Ae(s[a],2),d=l[0],u=l[1],i=(0,c.NA)(i,u,d);
 (0,p.P7)(i,!0)(re).then(function(e){
   re({type:m.u3,payload:Oe({},e.data.data)}),
   re({type:m.jC,payload:Oe(Oe({},st),{},{resume:t})})})
```

- Same shape: `value = {resume_file_id: <id>}`.
- `nn.current` is the in-flight upload promise; `o` is what it resolves to.

### The exact wire bytes for the resume_file_id form

VERIFIED. `NA` is this recursive bracket-flattener (`app.js`, same body also
inlined at the preferences call site and in `6461.dc650b9ab7317d42.js` as `oi`):

```js
F=function(e,t,n){if(!t||"object"!==_(t)||t instanceof Date||t instanceof File){
  var r=null==t?"":t;e.append(n,r)}
 else Object.keys(t).forEach(function(r){
  F(e,t[r],n?"".concat(n,"[").concat(r,"]"):r)});return e}
```

Applied to `{field:"resume_file_id", value:{resume_file_id:X}}` it emits exactly
two multipart parts:

```
field=resume_file_id
value[resume_file_id]=<file_id>
```

DERIVED (mechanical application of the quoted function; not separately observed
on the wire, since no request was made).

### A 6th path the brief did not ask about - flagged because it can clobber

VERIFIED: three `field="preferences"` call sites (`app.js` @1691805, @3425272;
`2764` @121254) fold the resume INTO the preferences value object:

```js
O||(on&&(d.resume=on),l&&(d.resume_file_id=l))     // app.js
ht&&(l.resume=ht),s&&(l.resume_file_id=s)          // app.js
l&&(u.resume_file_id=l)                            // app.js
```

Guarded by in-session upload state, so a plain preferences save carries no
resume. Relevant to the build only as a "do not blindly mirror the preferences
payload" warning.

---

## 2. Is profile-upsert the uploader, or only the pointer-setter?

**BOTH - there are two distinct sequences, and which one runs depends on the
screen.** VERIFIED.

### Sequence A - the profile page (R2): ONE call, upsert IS the uploader

```
POST talent/profile-upsert           multipart
     field=resume
     value=<binary file part>        (pdf/docx, <=2MB)
     [tid=<id>]                      only when impersonating
```

No `generate-upload-url`, no presigned PUT, no second call. The full ordered
sequence the profile page performs is that single request, and on success it
only mutates local redux and closes the editor.

### Sequence B - resume-editor / preferences (RFI1, RFI2): 3 ordered calls

VERIFIED from `app.js` around @1696553 and `2764` @255734:

```
1. POST talent/generate-upload-url   {file_type:"pdf"|"docx"}
      -> 200 {data:{file_id, url}}          url = a presigned PUT target
2. PUT  <url>                        raw file bytes
      headers: {"Content-Type": file.type}
      body: <the File>                      goes DIRECT to object storage,
                                            not through the Uplers API
3. POST talent/profile-upsert        multipart
      field=resume_file_id
      value[resume_file_id]=<file_id from step 1>
```

Quoted, step 1->2 (`app.js`):

```js
s=(0,p.rA)({file_type:a},!0)(re).then(function(){...
  return dn(t.data.file_id),e.n=1,
  fetch(t.data.url,{method:"PUT",headers:{"Content-Type":r.type},body:r})
  ... case 1: return e.a(2,t.data.file_id);   // promise resolves to file_id
}),  nn.current=s, O&&pn(r);                  // pn = step 3
```

### The other candidate routes, resolved

| route | what it actually is | verdict |
|---|---|---|
| `talent/resume-health-check/update-resume-in-profile` (`JkU`/`_x`) | **an HTML-to-PDF RENDER + file_id mint**, NOT the attacher. Called with `{transformation_id, page_count, type:"pdf", html:"<!DOCTYPE html>..."}`; returns `{data:{blob, url, file_id}}`. The client then PUTs and calls profile-upsert. VERIFIED, exactly 1 call site (`2764`). | not the attacher |
| `talent/tailor/preview-uploaded-resume` (`MRk`) | POST `{file_name:<base_resume>}` -> `.data.data`; a **preview by filename** in the tailor dashboard. VERIFIED, `5018`. | read-only preview |
| `talent/resume-health-check/preview-uploaded-resume` (`UpE`) | RHC-scoped preview. | read-only preview |
| `career-coach/upload-resume`, `career-coach/get-resume` | a **separate product surface** - VERIFIED, they authenticate with `Bearer localStorage.getItem("cc_token")`, not the talent session. | different product, not the profile resume |
| `talent/outreach/update-tailor-resume` | outreach-scoped tailored-resume pointer. | not the profile resume |

---

## 3. THE ROLLBACK QUESTION

### Verdict

**A rollback IS possible, but ONLY as a pre-flight snapshot plus a re-upload.
There is no server-side revert, no history, no version list, and no
re-submittable pointer. The snapshot MUST be captured BEFORE the write; if the
replacement happens first, nothing in the client bundle can reach the old file.**

### 3a. Does the platform keep the previous resume?

**Nothing in the bundle says it does.** VERIFIED absences (grep over all 86
files): `resume_history` 0, `resume_versions` 0, `previous_resume` 0,
`old_resume` 0, `resume_archive` 0. `resume_url` 0, `resume_path` 0,
`resume_link` 0.

One genuine UNRESOLVED. `resume_list` (the tailor feature's source-resume
picker, redux slice `resumeEditor`) has three categories, and the "profile" one
is rendered by a `.map()` over a filtered array with `created_at` shown as
*"Last updated ..."*. VERIFIED, `2764`:

```js
s.filter(function(e){return"profile"==e.list_type}).map(function(e,t){...
  ["Profile Resume | ",e.label] ... ["Last updated ",(0,j.Jo)(e.created_at)]
},"profile-resume-"+t)
```

Items are keyed by the composite `source_resume_id + "xid" + source_type`.
INFERRED (weak-to-moderate): a `.map()` with an index key over a filtered
category suggests the category CAN hold more than one entry, which would mean
prior profile resumes survive somewhere. **UNRESOLVED - whether it ever holds
more than one entry is server data, and a client bundle cannot settle it. Do not
build any rollback on this.**

### 3b. Can the CURRENT resume be read back as a file before replacing? YES

**This is the load-bearing finding.** VERIFIED, `app.js`:

```js
Se=function(e){var t=...;return function(n){return new Promise(function(r,s){
  t||n({type:a.rQ,payload:!0}),
  (0,i.Yr)(o.f5v+"?talent_id="+e).then(function(e){r(e)})
```

`GET talent/talent-download-resume-profile?talent_id=<talent_enc_id>`

- **Only ONE parameter: `talent_id`.** There is no resume-id, version, or
  revision parameter. It always returns THE CURRENT resume. That is precisely
  what a pre-flight snapshot needs, and precisely why post-hoc recovery is
  impossible.
- **It returns BYTES, not a URL.** VERIFIED from all 4 consumers, which do:

```js
i=e.data.data, a=e.data.blob, s=e.data.ext, l=e.data.filename;
"pdf"===s?((a=(0,c.i)(a,"application/pdf")).name=l,i=URL.createObjectURL(a))
:"docx"===s&&((a=(0,c.i)(a,"application/vnd.openxmlformats-officedocument.wordprocessingml.document")).name=l,i=URL.createObjectURL(a));
```

  and `(0,c.i)` is a **base64 decoder** - VERIFIED, its body is:

```js
function v(e,t){for(var n=atob(e),r=[],o=0;o<n.length;o+=512){
  for(var i=n.slice(o,o+512),a=new Array(i.length),s=0;s<i.length;s++)
    a[s]=i.charCodeAt(s);var l=new Uint8Array(a);r.push(l)}
 return new Blob(r,{type:t})}
```

  So the response is JSON `{blob:"<base64>", ext:"pdf"|"docx", filename:"<name>", data:...}`
  and `blob` is **the actual resume file, base64-encoded**.
- `talent_id` is the caller's own `talent_enc_id` (VERIFIED: consumers pass
  `de.talent_enc_id` / `K.talent_enc_id` off the auth user).

### 3c. Is there a DELETE / revert / restore for a resume? NO

VERIFIED. `talent/profile/delete-details` exists and is the only profile delete,
but it is called with exactly six section names and **never with a resume**:

```
qpI,{name:"achievements"}  {name:"certifications"}  {name:"educations"}
qpI,{name:"experiences"}   {name:"projects"}        {name:"testimonials"}
```

A grep of every quoted route-shaped string in the corpus containing "resume"
returns no delete/revert/restore/undo route. (`btn-remove-resume` is a CSS class
only.)

### 3d. Is the stored pointer durable and re-submittable? NO

**This is what kills the cheap rollback.** VERIFIED: `resume_file_id` appears 8
times in the entire corpus (5 in `app.js`, 3 in `2764`) and **all 8 are WRITES**
- assignments into an outgoing payload. It is never read from a profile
response, never rendered, never stored into redux from server data. A grep for
any read of `.resume_file_id` returns zero hits.

INFERRED (strong): `file_id` is a **one-shot upload token** minted by
`generate-upload-url` and consumed by `profile-upsert`. It is not a durable
handle the client is ever given back, so "read the current pointer, keep it,
write it back later" is **not available**.

What the profile DOES expose is `resume` - a plain **filename string**
(consumed as `preferencesData?.resume` and rendered / `.split(".")`-ed). You
cannot write that back: the `field="resume"` path requires an actual file part,
and its 422 error channel is `errors.value` with the message *"The resume must
be a file of type: pdf, docx."*

### 3e. The practical answer

**A rollback is possible by this exact sequence:**

```
BEFORE any write:
  1. GET talent/talent-download-resume-profile?talent_id=<talent_enc_id>
  2. base64-decode response.data.blob  -> save to disk together with
     response.data.filename and response.data.ext        <-- THE BACKUP

Then the replacement:
  3. POST talent/profile-upsert  (multipart)
       field=resume
       value=<new file>

To undo, at any later time:
  4. POST talent/profile-upsert  (multipart)
       field=resume
       value=<the bytes saved in step 2, sent as a file part
              named response.data.filename>
```

Constraints that must be stated to the operator before anything is built:

- **Step 1 is not optional and cannot be done afterwards.** There is no history,
  no version list, no archive, and the download route takes no
  "which resume" parameter. Miss the snapshot and the old file is gone from
  everything the client can see.
- The undo is a **fresh upload**, not a revert. Server-side identity
  (`file_id`, `created_at`, any derived RHC/tailor state) will be new. The
  BYTES are restored; the record is not.
- The saved file must still satisfy the client-side gate (pdf/docx, <=2MB),
  which the original necessarily did.
- INFERRED, not verified: step 4 restores what a reader sees. Whether any
  server-side derived artifact (health score, parsed profile) is recomputed to
  its former value is not determinable from a client bundle.

---

## 4. Blast radius

### What the UI does after a successful replacement (VERIFIED, client-side only)

| site | after success |
|---|---|
| R2 (profile page) | `A({type:d.u3,payload:{resume:e.data.data}})` then `T()` (close editor). **Nothing else** - no refetch, no toast, no navigation. |
| R1 / R3 (RHC nudge) | `(0,c.lq)(!1)` = **refetch `user/me`**; success toast; redux `resume` update; analytics `y6(file.name)`. |
| RFI1 (resume editor) | redux update; `sessionStorage.setItem("fetchLatestResume",true)`; toast; `(0,w.lq)(!1)` = refetch `user/me`. |
| RFI2 (preferences) | redux update only. |

`fetchLatestResume` is VERIFIED as a pure client cache-buster: the preferences
page checks `!sessionStorage.getItem("fetchLatestResume")` and, when the flag is
set, removes it and refetches fresh profile data instead of using cached redux.
`resume_just_updated` is likewise a client-only redux flag that suppresses the
tailor resume-picker dropdown.

### Server-side effects that ARE named in the code

1. **Profile completion is recomputed.** VERIFIED - the dispatcher reads
   `e.data.profile_completion_percentage` and
   `e.data.profile_remaining_percentage` off every profile-upsert response.
2. **`is_resume_updated` flips on the RHC transform** when
   `transformation_file_id` is supplied (R1/R3 only). VERIFIED, the nudge modal
   is gated on `e.transform.status>=3 && 0===e.transform.is_resume_updated`.
   The plain profile-page path (R2) sends no `transformation_file_id` and so
   does not touch it.

### What could NOT be determined

**UNRESOLVED**: whether replacing the resume triggers a server-side re-parse of
the profile, re-scoring, any recruiter notification, or any effect on already
submitted applications. Nothing in the bundle names such an effect - there is no
re-parse trigger, no notification call, and no application-invalidation call
anywhere on the resume write paths (the 24 `reparse` hits in `app.js` are
moment.js locale definitions, not resume code). But **absence in a client bundle
is not evidence of absence on the server**, and this class of effect is exactly
the kind that lives server-side. This must not be reported to the operator as
"safe".

---

## 5. Preconditions

### Client-side validation, VERIFIED (identical across all resume inputs)

| gate | value | source |
|---|---|---|
| accept attribute | `.pdf,.docx` | `<input type="file" accept=".docx,.pdf">` |
| extension check | regex against the filename; failure message *"The resume must be a file of type: pdf, docx."* | `R.exec(w.resume)` / `F.exec(n.name)` |
| size limit | `n.size/1024>2048` -> **2 MB**; message *"File size should be less than 2 MB"* | all 5 sites |
| password-protected | an async precheck `(0,o.HY)(file)` runs BEFORE upload and aborts on throw: *"File is password-protected please upload unprotected file"*, and clears the input | R1/R3 handler, and the app.js paths |
| empty | *"Please add your resume"* / *"Please add a resume file"* | R1/R2 |

INFERRED: the 2 MB and pdf/docx limits are almost certainly enforced
server-side too - the 422 channel `e.response.data.errors.value` is wired up on
every site specifically to surface a server rejection of `value`.

### Required fields per path

| path | required | optional |
|---|---|---|
| Sequence A (profile page) | `field="resume"`, `value=<file>` | `tid` |
| Sequence B step 1 | `file_type` (the lowercased extension) | - |
| Sequence B step 3 | `field="resume_file_id"`, `value[resume_file_id]` | - |
| R1/R3 (RHC) | `field`, `value`, `transformation_file_id` | - |

### Is `tid` needed?

**No, not for the operator's own session.** VERIFIED: `tid` is read from the URL
query string - the profile page does
`null!==A.get("tid")&&(r+="/"+A.get("tid"),h(A.get("tid")))` where `A` is the
search-params hook. It is an impersonation / staff-viewing-a-talent parameter.
Acting as oneself, it is absent and is simply not appended
(`m&&n.append("tid",m)`).

---

## 6. Recommendation for the build decision

The write is buildable and its shape is fully determined. The one thing that
must be built WITH it, not after it, is the snapshot step - a resume replace
tool that does not first capture and persist
`talent/talent-download-resume-profile` bytes is a genuine one-way door.

Recommend Sequence A (single multipart call, `field=resume`, `value=<file>`) for
a profile resume replacement: it is the path the profile page itself uses, it
needs no presigned-PUT handling, and it does not touch RHC transform state.

Two things to settle before shipping, neither of which a bundle can answer:

1. Whether `resume_list` ever returns more than one `list_type=="profile"`
   entry. If it does, a real post-hoc recovery may exist and is worth exposing.
   One authenticated read of the tailor dashboard settles it.
2. Whether the server does anything on resume replace beyond recomputing
   profile completion. Unknowable from static analysis; treat as unknown.
