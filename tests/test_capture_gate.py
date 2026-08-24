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
