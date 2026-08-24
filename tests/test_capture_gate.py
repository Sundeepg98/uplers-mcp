"""Controls over the leak gate in `scripts/capture_outreach.py`.

Two defects, both found during a live capture on 2026-08-24, and one control
per mechanism. Every control here was watched RED against the unfixed code
before the fix landed. A check that has never been shown failing certifies
nothing, so a control that passes on the broken code is a broken control.

  DEFECT 1 -- THE GATE REPORTED BEFORE IT DELETED. `write_fixture` scanned the
  file it had just written, the caller printed the verdict, and only then
  unlinked. A `BrokenPipeError` inside that print skipped the unlink, and a
  fixture holding a real LinkedIn profile URL survived on disk until it was
  removed by hand. The same print had already raised once before, on
  2026-08-23, as a `UnicodeEncodeError` from an emoji on a cp1252 console.
  Two firings, two unrelated causes, one ordering bug.

  DEFECT 2 -- `resumePath` WAS AN UNCAUGHT PII CLASS.
  `talent/outreach/preview-config` answers `$.data.resumePath.url`: a
  presigned S3 URL, which is a BEARER CREDENTIAL rather than a reference --
  whoever holds the string downloads the document until the signature
  expires. Nothing caught it. `DROP` is a list of exact snake_case names and
  this key is camelCase with the URL one level down under `.url`, so the key
  layer could not see it and the value layer had no opinion about URLs at
  all.

NO REAL VALUE APPEARS IN THIS FILE. The presigned URLs below are synthesised
to the right shape with an all-zero (or all-one) signature, and the LinkedIn
slug carries a token `tests/test_pii_hygiene.py` recognises as invented --
the same rule that module enforces over the whole repository.
"""

from __future__ import annotations

import asyncio
import json

import pytest

import capture_agent_surface
import capture_outreach

# --------------------------------------------------------------------------
# Synthetic payloads
# --------------------------------------------------------------------------

#: Reproduces the shape `preview-config` really answered: the URL is not the
#: value of a DROP-listed key, it is one level down under `.url`, and the key
#: holding it is camelCase.
PRESIGNED_RESUME_URL = (
    "https://ats-uplers.s3.amazonaws.com/resume/candidate-resume.pdf"
    "?X-Amz-Algorithm=AWS4-HMAC-SHA256"
    "&X-Amz-Credential=EXAMPLEFAKEKEYID%2F20260824%2Fap-south-1%2Fs3%2Faws4_request"
    "&X-Amz-Date=20260824T000000Z&X-Amz-Expires=604800"
    "&X-Amz-SignedHeaders=host"
    "&X-Amz-Signature=" + ("0" * 64)
)

#: A regional-endpoint spelling of the same host, under a DIFFERENT camelCase
#: key. Here so the controls pin the CLASS rather than the one string that was
#: measured.
PRESIGNED_PROFILE_URL = (
    "https://ats-uplers.s3.ap-south-1.amazonaws.com/profile/original-resume.pdf"
    "?X-Amz-Algorithm=AWS4-HMAC-SHA256"
    "&X-Amz-Credential=EXAMPLEFAKEKEYID%2F20260824%2Fap-south-1%2Fs3%2Faws4_request"
    "&X-Amz-Date=20260824T000000Z&X-Amz-Expires=604800"
    "&X-Amz-SignedHeaders=host"
    "&X-Amz-Signature=" + ("1" * 64)
)

#: Under a key NOBODY HAS ENUMERATED, which is the whole point of it. No
#: spelling of `DROP` can cover this one, so if the value never reaches disk it
#: is the value-shaped rule that stopped it and nothing else.
PRESIGNED_ATTACHMENT_URL = (
    "https://ats-uplers.s3.amazonaws.com/attachments/cover-letter.pdf"
    "?X-Amz-Signature=" + ("2" * 64)
)

#: An ordinary link on the platform's own site. Nothing about it is a
#: credential, and a rule that eats it is too wide.
ORDINARY_URL = "https://www.uplers.com/jobs/software-engineer/"

#: The 2026-08-24 incident in miniature: a contact route the CURRENT detector
#: already condemns, so the only thing DEFECT 1's controls measure is the
#: ORDERING, never the detector.
LEAKED_CONTACT_URL = "https://www.linkedin.com/in/a-real-person-0000"

LEAKING_BODY = {
    "status": 200,
    "data": {"employee_profile_link": LEAKED_CONTACT_URL},
}


def _boom(*args, **kwargs):
    """A `print` that fails the way the real one failed: a closed pipe."""
    raise BrokenPipeError(32, "Broken pipe")


class _StubSession:
    """Stands in for `SessionStore`. Never reads his real session file."""

    def token(self) -> str:
        return "stub-token-not-a-credential"


class _StubClient:
    """Stands in for `TalentClient`. Makes no request and opens no socket."""

    requests_made = 1

    def __init__(self, token=None, **kwargs):
        self._token = token

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def get_json(self, path, params=None):
        return LEAKING_BODY


def _written(path):
    """The fixture's text, or None when the gate deleted it."""
    if not path.exists():
        return None
    return path.read_text(encoding="utf-8")


# --------------------------------------------------------------------------
# DEFECT 1 -- the unlink must survive the report raising
# --------------------------------------------------------------------------


class TestALeakingFixtureNeverSurvivesAFailedReport:
    """The delete must not be reachable only after a print.

    Both controls drive the REAL gate with a payload that really leaks and a
    report step that really raises, then look at the filesystem. Neither
    inspects a return value, so both read identically against the code before
    and after the fix -- which is what let them be watched failing.
    """

    def test_capture_outreach_deletes_before_it_reports__CONTROL(
        self, tmp_path, monkeypatch
    ):
        """`capture_outreach.main()` -- the loop that leaked on 2026-08-24."""
        monkeypatch.setattr(capture_outreach, "OUT_DIR", tmp_path)
        monkeypatch.setattr(
            capture_outreach,
            "CAPTURES",
            (("probe", "talent/outreach/outreach-step", None),),
        )
        monkeypatch.setattr(
            capture_outreach, "ALLOWED", {"talent/outreach/outreach-step"}
        )
        monkeypatch.setattr(capture_outreach, "SessionStore", _StubSession)
        monkeypatch.setattr(capture_outreach, "TalentClient", _StubClient)
        # A module-level `print` shadows the builtin for this module only, so
        # the failure is scoped to the code under test exactly as a closed
        # stdout would scope it.
        monkeypatch.setattr(capture_outreach, "print", _boom, raising=False)

        with pytest.raises(BrokenPipeError):
            asyncio.run(capture_outreach.main())

        assert not (tmp_path / "probe.json").exists(), (
            "capture_outreach left a LEAKING fixture on disk after the report "
            "raised. The unlink must not be reachable only after a print: "
            "nothing that can fail may sit between the leak verdict and the "
            "delete."
        )

    def test_capture_agent_surface_deletes_before_it_reports__CONTROL(
        self, tmp_path, monkeypatch
    ):
        """The second copy of the same ordering, in `capture()`."""
        monkeypatch.setattr(capture_agent_surface, "OUT_DIR", tmp_path)
        monkeypatch.setattr(capture_agent_surface, "print", _boom, raising=False)

        with pytest.raises(BrokenPipeError):
            asyncio.run(
                capture_agent_surface.capture(
                    _StubClient(), "probe", "talent/outreach/get-auto-reply", None
                )
            )

        assert not (tmp_path / "probe.json").exists(), (
            "capture_agent_surface left a LEAKING fixture on disk after the "
            "report raised. The unlink must not be reachable only after a "
            "print."
        )

    def test_a_clean_fixture_still_survives__CONTROL(self, tmp_path, monkeypatch):
        """The delete-first ordering must not delete a CLEAN capture.

        Without this, a gate that unlinked unconditionally would pass both
        controls above while destroying every fixture the scripts exist to
        write.
        """
        monkeypatch.setattr(capture_agent_surface, "OUT_DIR", tmp_path)

        class _Clean(_StubClient):
            async def get_json(self, path, params=None):
                return {"status": 200, "data": {"gmail_connected": True}}

        asyncio.run(
            capture_agent_surface.capture(
                _Clean(), "probe", "talent/outreach/get-auto-reply", None
            )
        )
        assert (tmp_path / "probe.json").exists()
        assert json.loads(_written(tmp_path / "probe.json"))["data"] == {
            "gmail_connected": True
        }


# --------------------------------------------------------------------------
# DEFECT 2 -- a presigned object-storage URL is a credential
# --------------------------------------------------------------------------


class TestAPresignedUrlNeverReachesDisk:
    """Gate-level: drive `write_fixture` and then read the file back.

    Reading the FILE rather than the return value is deliberate twice over. It
    is what the incident was about -- bytes on disk, not a value in a variable
    -- and it keeps these controls independent of `write_fixture`'s signature,
    which the DEFECT 1 fix changes.
    """

    def test_a_presigned_resume_path_url_never_reaches_disk__CONTROL(self, tmp_path):
        """The measured miss: `$.data.resumePath.url` from `preview-config`."""
        target = tmp_path / "preview_config.json"
        capture_outreach.write_fixture(
            target,
            {
                "status": 200,
                "data": {
                    "HR_Number": "HR100725001919",
                    "resumePath": {
                        "url": PRESIGNED_RESUME_URL,
                        "name": "resume.pdf",
                    },
                },
            },
        )
        text = _written(target)
        assert text is not None, "the fixture was deleted; expected it scrubbed"
        assert "X-Amz-Signature" not in text, (
            "A presigned S3 URL reached disk under `resumePath.url`. That "
            "string is a bearer credential: it downloads his resume until it "
            "expires."
        )
        assert "s3.amazonaws.com" not in text
        assert "resumePath" not in text, (
            "`resumePath` survived redaction. The key layer must name the "
            "FIELD, not one of its spellings."
        )

    def test_a_camelcase_resume_sibling_never_reaches_disk__CONTROL(self, tmp_path):
        """The class, not the string: a camelCase sibling of a DROP entry."""
        target = tmp_path / "sibling.json"
        capture_outreach.write_fixture(
            target,
            {"data": {"originalResumeUrl": PRESIGNED_PROFILE_URL}},
        )
        text = _written(target)
        assert text is not None, "the fixture was deleted; expected it scrubbed"
        assert "X-Amz-Signature" not in text, (
            "A presigned S3 URL reached disk under `originalResumeUrl`. "
            "Appending the one measured key name leaves every other camelCase "
            "spelling exactly as exposed."
        )
        assert "amazonaws.com" not in text

    def test_a_presigned_url_under_an_unenumerated_key_is_masked__CONTROL(
        self, tmp_path
    ):
        """The load-bearing rule, isolated.

        `attachmentDownloadPath` is in no list and normalises onto no entry in
        `DROP`, so the key layer is structurally unable to catch it. Only a
        value-shaped rule can, which is why the value-shaped rule is the one
        that carries this fix.
        """
        target = tmp_path / "unknown_key.json"
        capture_outreach.write_fixture(
            target,
            {"data": {"attachmentDownloadPath": PRESIGNED_ATTACHMENT_URL}},
        )
        text = _written(target)
        assert text is not None, "the fixture was deleted; expected it scrubbed"
        assert "X-Amz-Signature" not in text, (
            "A presigned S3 URL reached disk under a key no list knows about. "
            "The value is the credential, so the rule has to read the value."
        )
        body = json.loads(text)
        assert "attachmentDownloadPath" in body["data"], (
            "the unknown key was deleted rather than masked -- the shape a "
            "fixture exists to pin was thrown away with the credential"
        )

    def test_the_detector_flags_a_presigned_url_buried_in_prose__CONTROL(self):
        """A URL inside an HTML body CONDEMNS the fixture instead of being
        half-scrubbed.

        This is the same line `capture_agent_surface.py` already draws around
        `get-recommended-jobs`: scrubbing inside free text is a much weaker
        guarantee than key-based redaction, so free text carrying a credential
        is a reason to delete the file, not to rewrite it.
        """
        prose = (
            "<p>Download the CV here: <a href=\"%s\">CV</a></p>"
            % PRESIGNED_RESUME_URL
        )
        leaks = list(capture_outreach.contact_leaks({"description": prose}))
        assert leaks, (
            "the leak detector did not flag a presigned object-storage URL "
            "embedded in a free-text body -- so the fixture would have been "
            "reported clean and committed"
        )
        assert leaks[0][0] == "credential-url"
        assert leaks[0][1] == "$.description"

    def test_the_replacement_placeholder_is_not_itself_a_leak__CONTROL(self):
        """The value the masker writes must not trip the detector it feeds.

        A placeholder that fires the scan would delete every fixture it
        touched, turning the fix into an outage.
        """
        placeholder = capture_outreach.CREDENTIAL_URL_PLACEHOLDER % 1
        assert not list(capture_outreach.contact_leaks({"url": placeholder}))
        assert placeholder.endswith("-1")


class TestTheRuleIsNarrowEnoughToBeUseful:
    """Over-reach guards. A rule that eats everything protects nothing.

    Neither of these could be watched failing against the SHIPPED code, and
    they are labelled GUARD rather than CONTROL for exactly that reason. Both
    were watched failing against the naive fix they exist to rule out -- a key
    rule that drops any key containing "resume", and a value rule that
    rewrites any URL.
    """

    def test_an_ordinary_https_url_is_left_alone__GUARD(self, tmp_path):
        target = tmp_path / "ordinary.json"
        capture_outreach.write_fixture(target, {"data": {"job_url": ORDINARY_URL}})
        assert json.loads(_written(target))["data"]["job_url"] == ORDINARY_URL

    def test_a_status_field_named_after_the_resume_survives__GUARD(self, tmp_path):
        """`video_resume_status` and `share_video_resume` are committed today.

        They are flags, not documents. A key rule wide enough to swallow them
        would silently empty eleven fixtures on the next recapture.
        """
        target = tmp_path / "flags.json"
        capture_outreach.write_fixture(
            target,
            {
                "data": {
                    "video_resume_status": "active",
                    "share_video_resume": 1,
                    "total_tailored_resumes": 7,
                }
            },
        )
        body = json.loads(_written(target))["data"]
        assert body["video_resume_status"] == "active"
        assert body["share_video_resume"] == 1
        assert body["total_tailored_resumes"] == 7


# ==========================================================================
# DEFECT 3 -- THE PROSE CLASS, THE OPAQUE-HANDLE CLASS, AND HANDLES IN URLs
# ==========================================================================
#
# Three classes measured across the published mirror on 2026-08-24, none of
# which any rule above could see.
#
#   DEFECT 3 -- PROSE WAS NEVER WALKED. `outreach_missed_followups.json` had
#   every STRUCTURED contact field correctly substituted and still named four
#   real people, because `message_full` and `reply_summary` carried quoted
#   reply bodies with intact email signature blocks. The structured scrub is
#   what made it dangerous: the shaped fields read as synthetic, so the file
#   looked safe to anyone who opened it. THE SCRUB WAS A DECOY.
#
#   DEFECT 4 -- 142 OPAQUE HANDLES HAD NO SHAPE TO CATCH. `enc_id`,
#   `talent_id`, `user_id`, `gmail_thread_id`, and the third-party
#   `outreach_employee_id` and `created_by`/`published_by`/`closed_by`/`ta_id`
#   actor ids. The sibling specimen proves the failure exactly: every field
#   with a personal SHAPE was substituted and `outreach_employee_id` was kept
#   verbatim, so the "sanitised" file still names the same seven real people.
#
#   DEFECT 5 -- A HANDLE CAN RIDE INSIDE A URL UNDER NO KEY AT ALL. `ouid=` in
#   an ordinary Google Docs link, and a 43-character signature parameter called
#   `t`. The census scanner missed both on its first pass and fixed it by
#   parsing every query string rather than by lengthening a parameter list.
#
# NO REAL VALUE APPEARS BELOW. Every plant is synthetic by construction: the
# NANP numbers use the 555-01xx range the NANP reserves for fiction, which is
# the telephone equivalent of the `.invalid` TLD used elsewhere in this file;
# the names carry a synthetic token; the handles are visibly patterned rather
# than random. Each plant is removed with the tmp_path that holds it and is
# never written to a tracked fixture.

# --------------------------------------------------------------------------
# Synthetic plants
# --------------------------------------------------------------------------

#: A signature block of the kind that survived the structured scrub: a given
#: name, a title, an employer and a number, under a closing word.
SIGNOFF_REAL_NEWLINES = (
    "Thanks for reaching out, this looks interesting.\n\n"
    "Regards,\n"
    "Testperson\n"
    "Head of Placeholder Engineering, Example Stub Ltd\n"
    "555-555-0147\n"
)

#: THE SAME BLOCK IN THE FORM IT ACTUALLY OCCURS IN. Inside a JSON string a
#: line break is the two characters backslash-r backslash-n on one physical
#: line, and EVERY REAL SIGN-OFF IN THIS REPOSITORY IS IN THAT FORM. A pattern
#: anchored on a real newline sees none of them, which is why both forms are
#: planted and both must fire.
SIGNOFF_JSON_ESCAPED = (
    "Thanks for reaching out, this looks interesting.\\r\\n\\r\\n"
    "Regards,\\r\\n"
    "Testperson\\r\\n"
    "Head of Placeholder Engineering, Example Stub Ltd\\r\\n"
    "555-555-0147\\r\\n"
)

#: A NANP number on its own. Both inherited phone shapes assume an Indian
#: mobile or a leading plus sign, so this run was invisible to both.
PHONE_NANP_PLANT = "555-555-0182"

#: `alnum(32)`, the shape of every `enc_id` in this repository. Patterned so a
#: reader can see it is invented, and so the per-position character CLASS is
#: known: lower, upper, digit, repeating.
ENC_ID_PLANT = "aB3" * 10 + "cD"
#: A second 32-char handle, distinct from the one above, for planting at a
#: PERSON path. Two plants are needed because one key name covers two
#: subjects -- see the sibling-capture control.
PERSON_ENC_ID_PLANT = "zY7" * 10 + "wX"

#: `alnum_dash(17)`, the shape of a Gmail thread id. The dash position is the
#: part a shape-preserving substitute has to keep.
THREAD_ID_PLANT = "aaaa1111-bbbb2222"

#: A Google Docs share link carrying `ouid=`, Google's obfuscated account id
#: for whoever shared the document. Under a key called `JDURL`, where a
#: reviewer reads "a link to the JD" and moves on.
OUID_PLANT = "1" * 21
JD_URL_WITH_OUID = (
    "https://docs.google.com/document/d/1AAAABBBBCCCCDDDDEEEEFFFFGGGG/edit"
    "?usp=sharing&ouid=%s&rtpof=true&sd=true" % OUID_PLANT
)

#: A signed image URL whose signature parameter is called `t`. Nothing on any
#: enumerated parameter list is named `t`, which is exactly why 80 of these
#: went unseen on a first pass.
SIGNATURE_T_PLANT = "AAAA1111BBBB2222CCCC3333DDDD4444EEEE5555FFF"
LOGO_URL_WITH_T = (
    "https://media.licdn.com/dms/image/v2/AAAA/company-logo_200_200/0/1700000000000"
    "?e=1757505600&v=beta&t=%s" % SIGNATURE_T_PLANT
)

#: Ordinary query parameters that a rule wide enough to be useful must still
#: leave alone. A ten-digit posting id is the documented false-positive
#: neighbour of every id shape in this project.
ORDINARY_QUERY_URL = (
    "https://www.uplers.com/jobs/software-engineer/"
    "?sort=date_posted&page=1&utm_campaign=spring_hiring&gh_jid=1234567890"
)


def _classes(text):
    """Per-position character class, which is what "same shape" means here."""
    out = []
    for char in text:
        if "0" <= char <= "9":
            out.append("d")
        elif "a" <= char <= "z":
            out.append("l")
        elif "A" <= char <= "Z":
            out.append("u")
        else:
            out.append(char)
    return "".join(out)


# --------------------------------------------------------------------------
# CLASS 1 -- prose is DELETED, never pattern-scrubbed
# --------------------------------------------------------------------------


class TestProseFieldsAreDeletedNotScrubbed:
    """The measured 2026-08-24 leak, per field, at the gate.

    Each control drives the REAL `write_fixture` with a payload shaped like the
    route's own answer, then reads the FILE back. Reading the file is the point:
    the incident was bytes on disk, not a value in a variable.
    """

    def test_message_full_is_deleted__CONTROL(self, tmp_path):
        """The field that carried the signature blocks."""
        target = tmp_path / "missed.json"
        capture_outreach.write_fixture(
            target,
            {"data": {"rows": [{
                "reply_category": "positive",
                "message_full": SIGNOFF_JSON_ESCAPED,
            }]}},
        )
        text = _written(target)
        assert text is not None, "the fixture was deleted; expected it scrubbed"
        assert "message_full" not in text, (
            "`message_full` survived redaction. A mask over prose relies on "
            "the placeholder being written every time; deleting the key needs "
            "no enumeration of what a signature block can contain."
        )
        assert "Testperson" not in text
        assert "555-555-0147" not in text
        assert json.loads(text)["data"]["rows"][0]["reply_category"] == "positive", (
            "the platform-generated enum was thrown away with the prose -- it "
            "is the field the shaper actually reads"
        )

    def test_reply_summary_is_deleted__CONTROL(self, tmp_path):
        """The second prose field of the same row."""
        target = tmp_path / "missed.json"
        capture_outreach.write_fixture(
            target,
            {"data": {"rows": [{"reply_summary": SIGNOFF_REAL_NEWLINES}]}},
        )
        text = _written(target)
        assert text is not None, "the fixture was deleted; expected it scrubbed"
        assert "reply_summary" not in text
        assert "Testperson" not in text

    def test_company_pitch_is_deleted__CONTROL(self, tmp_path):
        """CLASS 5 -- the three identity findings that are LIVE AT HEAD.

        All three sit in `company_pitch`, in `talent_feed.json` and
        `talent_pipeline.json`: real people named as a team lead, a founder and
        a CEO/CTO, each with a biographical sentence. They were located by
        recomputing the census's published sha256 handles against the working
        tree, so the key was found without any value being read.

        A name has no lexical shape, so no value rule can reach them. Deleting
        the field that holds them is the only rule that does, and the field has
        zero readers in the server and zero in the suite.
        """
        target = tmp_path / "feed.json"
        capture_outreach.write_fixture(
            target,
            {"hrs": {"data": [{
                "job_title": "Senior Backend Engineer",
                "company_pitch": (
                    "Founded in 2019, the team is led by Testperson Placeholder, "
                    "who was previously a director at Example Stub Ltd."
                ),
            }]}},
        )
        text = _written(target)
        assert text is not None, "the fixture was deleted; expected it scrubbed"
        assert "company_pitch" not in text
        assert "Testperson" not in text
        assert json.loads(text)["hrs"]["data"][0]["job_title"] == (
            "Senior Backend Engineer"
        ), "the surrounding row was thrown away with the prose field"

    def test_a_prose_field_with_a_live_reader_condemns_instead__CONTROL(self, tmp_path):
        """The half of the prose class that CANNOT be deleted.

        `description`, `about`, `JobDescription` and `title` have live readers
        and live assertions, so deleting them would empty the surfaces the
        fixtures exist to pin. They are not pattern-scrubbed either -- a
        signature block in one of them DELETES THE FIXTURE and asks a human,
        which is the correct outcome for text nobody can safely rewrite.

        This is the same line `contact_leaks` already draws around a credential
        URL buried in an HTML body.
        """
        target = tmp_path / "job.json"
        capture_outreach.write_fixture(
            target,
            {"data": {"description": SIGNOFF_JSON_ESCAPED}},
        )
        assert _written(target) is None, (
            "a fixture whose free text carries an intact signature block "
            "SURVIVED on disk. Prose with a live reader cannot be deleted and "
            "must not be half-cleaned, so the only correct outcome is that the "
            "capture refuses to leave the file behind."
        )


# --------------------------------------------------------------------------
# CLASS 2 -- opaque handles are REPLACED, shape intact
# --------------------------------------------------------------------------


class TestOpaqueHandlesAreReplacedNotDropped:
    """A handle with no shape, under a key that reads like an artefact.

    The sibling specimen is the calibration: every field with a personal SHAPE
    was substituted and `outreach_employee_id` was kept verbatim, so the
    sanitised file still named the same seven real people.
    """

    def test_an_enc_id_is_replaced_and_keeps_its_shape__CONTROL(self, tmp_path):
        """`$.talent_details.enc_id` -- the one handle PROVEN live.

        `resume_write.talent_enc_id()` sends exactly this string to the route
        that downloads his resume, and that route takes one parameter.
        """
        target = tmp_path / "profile.json"
        capture_outreach.write_fixture(
            target, {"talent_details": {"enc_id": ENC_ID_PLANT}}
        )
        text = _written(target)
        assert text is not None, "the fixture was deleted; expected it scrubbed"
        assert ENC_ID_PLANT not in text, (
            "the account handle reached disk verbatim. No shape check can see "
            "it, so only a key rule can."
        )
        written = json.loads(text)["talent_details"]["enc_id"]
        assert written != ENC_ID_PLANT
        assert len(written) == len(ENC_ID_PLANT) == 32
        assert _classes(written) == _classes(ENC_ID_PLANT), (
            "the substitute changed the SHAPE. A fixture exists to pin the "
            "shape Uplers really sends; a replacement that is not "
            "character-class-identical has thrown that away with the value."
        )

    def test_a_numeric_account_id_stays_a_number_of_the_same_width__CONTROL(
        self, tmp_path
    ):
        """`talent_id` -- one value, 210 rows. The cardinality IS the finding.

        A column with 210 rows and one value is not a foreign key into a
        catalog, it is the identity of the one account every row belongs to.
        """
        target = tmp_path / "rows.json"
        capture_outreach.write_fixture(
            target, {"data": {"rows": [{"talent_id": 1234567, "user_id": 7654321}]}}
        )
        row = json.loads(_written(target))["data"]["rows"][0]
        assert row["talent_id"] != 1234567
        assert isinstance(row["talent_id"], int), (
            "a seven-digit integer came back as a string -- the JSON TYPE is "
            "part of the shape a fixture pins"
        )
        assert len(str(row["talent_id"])) == 7, (
            "the substitute lost a digit. A leading zero silently narrows an "
            "id, so the first digit is drawn from 1-9 for an int."
        )
        assert row["user_id"] != 7654321

    def test_third_party_ids_are_replaced__CONTROL(self, tmp_path):
        """The severe ownership case, and the actor ids nobody enumerates.

        `outreach_employee_id` names seven real people; `created_by`,
        `published_by`, `closed_by` and `ta_id` name twenty Uplers staff. These
        are not the operator's ids to publish and consent was never his to
        give. No published identifier list contains "_by columns", which is
        exactly why they were still here.
        """
        target = tmp_path / "rows.json"
        capture_outreach.write_fixture(
            target,
            {"data": {"rows": [{
                "outreach_employee_id": 123456,
                "talent_gmail_email_id": 654321,
                "gmail_thread_id": THREAD_ID_PLANT,
                "created_by": 1234567,
                "published_by": 2345678,
                "closed_by": 3456789,
                "ta_id": 4567890,
            }]}},
        )
        text = _written(target)
        row = json.loads(text)["data"]["rows"][0]
        for key, planted in (
            ("outreach_employee_id", 123456),
            ("talent_gmail_email_id", 654321),
            ("gmail_thread_id", THREAD_ID_PLANT),
            ("created_by", 1234567),
            ("published_by", 2345678),
            ("closed_by", 3456789),
            ("ta_id", 4567890),
        ):
            assert key in row, "%s was deleted rather than replaced" % key
            assert row[key] != planted, "%s reached disk verbatim" % key
        assert THREAD_ID_PLANT not in text
        assert _classes(row["gmail_thread_id"]) == _classes(THREAD_ID_PLANT), (
            "the dash moved. `alnum_dash(17)` means the separator keeps its "
            "position, not merely that the length matches."
        )

    def test_the_same_handle_maps_the_same_way_everywhere__CONTROL(self, tmp_path):
        """REFERENTIAL INTEGRITY, which is why the substitute is derived from
        the VALUE and not from a per-document counter.

        The 210 rows that shared one `talent_id` across four fixtures have to
        go on sharing one, or every join a fixture exists to exercise breaks.
        """
        first = tmp_path / "a.json"
        second = tmp_path / "b.json"
        capture_outreach.write_fixture(first, {"talent": {"enc_id": ENC_ID_PLANT}})
        capture_outreach.write_fixture(
            second, {"data": {"rows": [{"enc_id": ENC_ID_PLANT, "talent_id": 1234567}]}}
        )
        a = json.loads(_written(first))["talent"]["enc_id"]
        b = json.loads(_written(second))["data"]["rows"][0]["enc_id"]
        # STATED FIRST, because without it this control CANNOT FAIL: a redactor
        # that substitutes nothing at all leaves the same original in both
        # files and satisfies `a == b` trivially. Watched passing that way
        # against the pre-change code before this line was added.
        assert a != ENC_ID_PLANT, "nothing was substituted, so equality is vacuous"
        assert a == b, (
            "the same original produced two different substitutes in two "
            "files. A counter-numbered placeholder does that, and it destroys "
            "every cross-fixture join."
        )

    def test_the_substitution_is_one_way_and_injective__CONTROL(self):
        """No inverse, and no two originals collapsing into one.

        A reversible substitution plus its table is the de-anonymisation
        artefact `test_pii_hygiene.test_no_mapping_table_of_real_values`
        forbids, so the mapping is a salted SHA-256 keystream with no table
        anywhere. Injectivity is the other half: a substitution that merges two
        people into one id has corrupted the data as well as scrubbed it.
        """
        originals = ["%07d" % n for n in range(500)]
        replaced = [capture_outreach.synthetic_like(v) for v in originals]

        assert len(set(replaced)) == len(originals), "the substitution collided"
        assert not set(replaced) & set(originals), "a value mapped to itself"
        # Applying it again does not walk back: there is no inverse to walk.
        assert capture_outreach.synthetic_like(replaced[0]) != originals[0]

    def test_a_sentinel_wearing_an_id_name_is_left_alone__GUARD(self, tmp_path):
        """`acceptance_by` and some `created_by` rows hold only 0 and 1.

        They are booleans wearing an id's name. Substituting one would corrupt
        a flag while pretending to protect a person, and it would inflate every
        count of "how many staff ids are in here". The floor that separates
        them is measured, not guessed: every real handle is six characters or
        longer and every sentinel is one.
        """
        target = tmp_path / "flags.json"
        capture_outreach.write_fixture(
            target,
            {"data": {"created_by": 0, "closed_by": 1, "enc_id": ""}},
        )
        body = json.loads(_written(target))["data"]
        assert body["created_by"] == 0
        assert body["closed_by"] == 1
        assert body["enc_id"] == "", "an empty handle was rewritten into a value"


# --------------------------------------------------------------------------
# CLASS 3 -- a handle inside a URL, under no key at all
# --------------------------------------------------------------------------


class TestHandlesInsideUrlsAreReplaced:
    """One level deeper than the value rule: inside the value.

    The rule is not a parameter list, deliberately. Both live examples were
    missed BY a parameter list, and the fix that held was to parse every query
    string and put every parameter through the same admission.
    """

    def test_an_ouid_inside_a_document_link_is_replaced__CONTROL(self, tmp_path):
        """`ouid=` is Google's obfuscated account id for whoever shared it.

        It rides under keys called `JDURL` and `jd_path`, which a reviewer
        classifies as "a link to the JD" and moves on. No key in this repo is
        named for it.
        """
        target = tmp_path / "hr.json"
        capture_outreach.write_fixture(
            target, {"detail": {"JDURL": JD_URL_WITH_OUID, "jd_path": JD_URL_WITH_OUID}}
        )
        text = _written(target)
        assert text is not None, "the fixture was deleted; expected it scrubbed"
        assert "ouid=%s" % OUID_PLANT not in text, (
            "a third party's Google account id reached disk inside an "
            "ordinary-looking link. The value has no shape AND no key -- only "
            "parsing the query string can reach it."
        )
        written = json.loads(text)["detail"]["JDURL"]
        assert "ouid=" in written, "the parameter was removed rather than rewritten"
        assert len(written) == len(JD_URL_WITH_OUID), (
            "the URL changed length -- the shape a fixture pins is the whole "
            "string, not just the parameter"
        )
        assert "usp=sharing" in written and "rtpof=true" in written, (
            "an untouched parameter was re-spelled. Re-serialising a query "
            "re-encodes parameters nobody asked about."
        )

    def test_a_signature_parameter_named_t_is_replaced__CONTROL(self, tmp_path):
        """80 unexpired signed URLs, signature parameter named `t`.

        Nothing on any enumerated parameter list is named `t`, which is exactly
        why a first pass saw none of them.
        """
        target = tmp_path / "jobs.json"
        capture_outreach.write_fixture(
            target, {"data": [{"company_logo": LOGO_URL_WITH_T}]}
        )
        text = _written(target)
        assert text is not None, "the fixture was deleted; expected it scrubbed"
        assert SIGNATURE_T_PLANT not in text, (
            "an unexpired signature reached disk under a one-letter parameter "
            "name. A rule that enumerates parameter names can only ever catch "
            "the names somebody already wrote down."
        )
        written = json.loads(text)["data"][0]["company_logo"]
        assert "e=1757505600" in written and "v=beta" in written, (
            "the expiry and version parameters were rewritten too -- neither "
            "is a handle, and a rule that eats them is too wide"
        )

    def test_ordinary_query_parameters_are_left_alone__GUARD(self, tmp_path):
        """A rule that eats every query string protects nothing.

        `gh_jid=` is the documented false-positive neighbour: a ten-digit
        posting id is structurally identical to an Indian mobile and to a
        six-to-seven digit account id, and it names nobody.
        """
        target = tmp_path / "ordinary.json"
        capture_outreach.write_fixture(
            target, {"data": {"apply_url": ORDINARY_QUERY_URL}}
        )
        assert json.loads(_written(target))["data"]["apply_url"] == ORDINARY_QUERY_URL


# --------------------------------------------------------------------------
# CLASS 4 -- the two shape gaps, in BOTH line-break forms
# --------------------------------------------------------------------------


class TestTheTwoShapeGapsFire:
    """A given name has no lexical shape and a NANP number had no pattern.

    Four of the nine third-party findings in this repository were invisible to
    every shape check that existed. They were found by a human reading a file
    all five checks had passed, and the order is worth recording: the
    instrument did not find them, a person did.
    """

    def test_a_signoff_fires_with_real_line_breaks__CONTROL(self):
        leaks = list(capture_outreach.contact_leaks(
            {"description": SIGNOFF_REAL_NEWLINES}
        ))
        assert leaks, (
            "an intact sign-off block was reported clean. A closing word "
            "followed by a line holding one or two capitalised words is the "
            "only handle a lone given name offers."
        )
        assert leaks[0][0] == "signoff-name"
        assert leaks[0][1] == "$.description"

    def test_a_signoff_fires_in_the_json_escaped_form__CONTROL(self):
        """The form that MATTERS, because it is the only form that occurs.

        Inside a JSON string a line break is the two characters backslash-r
        backslash-n on one physical line. Every real sign-off found in this
        repository is in that form, so a pattern anchored on a real newline
        would have reported all of them clean.
        """
        leaks = list(capture_outreach.contact_leaks(
            {"body": SIGNOFF_JSON_ESCAPED}
        ))
        assert leaks, (
            "a sign-off in the JSON-escaped form was reported clean -- which "
            "is the only form any real sign-off in this repository takes"
        )
        assert leaks[0][0] == "signoff-name"

    def test_a_nanp_phone_fires__CONTROL(self):
        """Both inherited phone shapes assume an Indian mobile or a plus sign.

        A US number written NNN-NNN-NNNN was invisible to both, and one was
        sitting in a signature block.
        """
        leaks = list(capture_outreach.contact_leaks(
            {"about": "Call the team on %s for details." % PHONE_NANP_PLANT}
        ))
        assert leaks, "a NANP-formatted number was reported clean"
        assert leaks[0][0] == "phone-nanp"

    def test_an_opaque_handle_buried_in_prose_condemns__CONTROL(self):
        """A URL in free text is CONDEMNED rather than rewritten.

        Scrubbing inside prose is a much weaker guarantee than key-based
        redaction, and the asymmetry is what keeps the redaction and the
        detector from fighting: a BARE url is rewritten and is then clean,
        while one buried in prose deletes the fixture.
        """
        prose = '<p>The JD lives <a href="%s">here</a>.</p>' % JD_URL_WITH_OUID
        leaks = list(capture_outreach.contact_leaks({"description": prose}))
        assert leaks, "an account handle inside a link inside prose was missed"
        assert leaks[0][0] == "opaque-url-param"

    def test_ordinary_prose_and_long_ids_do_not_fire__GUARD(self):
        """A detector that fires on everything deletes every fixture.

        The two cases that matter: job-advert prose with a closing word in the
        middle of a sentence, and a long numeric id that must not be sliced
        into a phone by a digit boundary.
        """
        benign = {
            "a": "Thanks to our partners, best in class delivery every quarter.",
            "b": "Requisition 15555550147999 is open until the end of the month.",
            "c": "Regards are due to the whole team for shipping on time.",
            "d": capture_outreach.CREDENTIAL_URL_PLACEHOLDER % 3,
        }
        assert not list(capture_outreach.contact_leaks(benign))

    def test_the_shape_preserving_substitute_is_not_itself_a_leak__CONTROL(
        self, tmp_path
    ):
        """The value the substituter writes must not trip the detector.

        A substitute that fired the scan would delete every fixture it touched,
        turning the fix into an outage. This is the live risk in a
        SHAPE-PRESERVING replacement specifically: unlike `rqyusjqy-nzllgg-2`,
        the output is deliberately indistinguishable in shape from the input.
        """
        target = tmp_path / "round_trip.json"
        capture_outreach.write_fixture(
            target,
            {"detail": {"JDURL": JD_URL_WITH_OUID},
             "data": [{"company_logo": LOGO_URL_WITH_T}],
             "talent": {"enc_id": ENC_ID_PLANT, "talent_id": 1234567}},
        )
        text = _written(target)
        assert text is not None, (
            "the gate deleted a fixture it had just cleaned -- the substitute "
            "is tripping the detector that feeds it"
        )
        # THE SUBSTITUTION MUST HAVE HAPPENED FIRST. Without these three lines
        # the control cannot fail: a redactor that rewrites nothing also
        # produces a file the detector reports clean, and it would sail through
        # the assertion below while leaking every value. Watched passing that
        # way against the pre-change code before they were added.
        assert ENC_ID_PLANT not in text
        assert OUID_PLANT not in text
        assert SIGNATURE_T_PLANT not in text
        assert not list(capture_outreach.contact_leaks(json.loads(text)))


# --------------------------------------------------------------------------
# THE PROPERTY THAT MATTERS MOST -- a surviving real value FAILS the gate
# --------------------------------------------------------------------------


class TestAFixtureCarryingARealValueFailsRatherThanReports:
    """Reporting a leak and leaving the file is not a gate, it is a log line.

    Every control here looks at the FILESYSTEM. None of them inspects a return
    value, because a return value is what a caller can ignore -- and on
    2026-08-24 a caller did exactly that when the report between the verdict and
    the unlink raised.
    """

    def test_write_fixture_deletes_a_fixture_with_a_surviving_leak__CONTROL(
        self, tmp_path
    ):
        """The leak class no redaction layer can rewrite: prose."""
        target = tmp_path / "leaky.json"
        size, leaks = capture_outreach.write_fixture(
            target, {"data": {"about": SIGNOFF_JSON_ESCAPED}}
        )
        assert leaks, "the gate did not even report the leak"
        assert _written(target) is None, (
            "the gate REPORTED a surviving leak and left the file on disk. A "
            "gate that reports is not a gate: the whole point of the "
            "2026-08-24 incident is that a leaking fixture must not exist once "
            "the call returns, however the caller behaves."
        )
        assert size > 0, "the size must be measured before the scan, not after"

    def test_the_sibling_capture_path_fails_the_same_way__CONTROL(
        self, tmp_path, monkeypatch
    ):
        """`capture_talent_rows.write` owns the two fixtures that carry the
        THREE identity findings live at HEAD.

        Before this wave it had its own weaker redaction: an exact-name key
        delete with no value rule at all -- no camelCase folding, no mask, no
        credential-URL rule, no opaque-handle rule. Two redactions of different
        strength is not redundancy, it is a hole with a second copy of the
        rules in front of it.
        """
        import capture_talent_rows

        monkeypatch.setattr(capture_talent_rows, "FIXTURES", tmp_path)

        with pytest.raises(SystemExit):
            capture_talent_rows.write(
                "probe", {"hrs": {"data": [{"description": SIGNOFF_JSON_ESCAPED}]}}
            )
        assert not (tmp_path / "probe.json").exists(), (
            "the sibling capture left a leaking fixture on disk. The delete "
            "must not be reachable only after a message is built."
        )

    def test_the_sibling_capture_applies_the_shared_redaction__CONTROL(
        self, tmp_path, monkeypatch
    ):
        """The other half: a payload the SHARED rules can clean is cleaned.

        Without this the control above would pass against a sibling that simply
        refused everything.
        """
        import capture_talent_rows

        monkeypatch.setattr(capture_talent_rows, "FIXTURES", tmp_path)
        capture_talent_rows.write(
            "probe",
            {"hrs": {"data": [{
                "job_title": "Senior Backend Engineer",
                "company_pitch": "Led by Testperson Placeholder, our founder.",
                "enc_id": ENC_ID_PLANT,
                "current_talent_hr": {"enc_id": PERSON_ENC_ID_PLANT},
                "talent_id": 1234567,
                "hr": {"company": {"company_logo": LOGO_URL_WITH_T}},
            }]}},
        )
        text = (tmp_path / "probe.json").read_text(encoding="utf-8")
        row = json.loads(text)["hrs"]["data"][0]
        assert "company_pitch" not in text
        assert "Testperson" not in text
        assert SIGNATURE_T_PLANT not in text
        assert json.loads(text)["hrs"]["data"][0]["job_title"] == (
            "Senior Backend Engineer"
        )

        # THE TWO enc_id PLANTS ARE THE POINT, and they sit at two paths that
        # wear the same key name and mean different things. Adjudicated
        # 2026-08-24 (`capture_outreach.PUBLIC_HANDLE_PATHS`): under
        # `hrs.data[]` an `enc_id` is a REQUISITION - a public job posting the
        # public tier already serves from Uplers' public sitemap with no
        # account at all - while the one hanging off `current_talent_hr` is HIS
        # application to it, and identifies him.
        #
        # Asserting only the first would test the carve-out; asserting only the
        # second would test the substitution. The control needs both, or a
        # future edit that widened the exemption over person paths would still
        # go green.
        assert PERSON_ENC_ID_PLANT not in text, (
            "a handle at a PERSON path survived the sibling capture"
        )
        assert row["enc_id"] == ENC_ID_PLANT, (
            "a REQUISITION handle was substituted -- that buys no privacy and "
            "breaks the identifier-space distinction Uplers' API actually makes"
        )
