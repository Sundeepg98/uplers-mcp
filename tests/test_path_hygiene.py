"""No tool result may publish this machine's directory layout.

REPRODUCED LIVE on 2026-08-22 against the running server: uplers_get_profile()
came back with `"path": "D:\\Sundeep\\projects\\job-hunting\\mcp-servers\\
uplers\\data\\profile.json"` and `"config_source":
"D:\\Sundeep\\projects\\job-hunting\\config\\jobhunt.json"`, and uplers_config()
leaked the same string in `source`, `status` and every entry of `searched`.

THE RULING IS RELATIVISE, NOT DELETE, and the distinction is the whole file.
"Where is the config file even?" is a documented use of uplers_config - its own
docstring says `searched` is how you find it - so a null in those fields trades
a leak for a different defect: a field that answers a different question than it
looks like. Every assertion below therefore comes in a pair. One says the path
carries no layout; the other says it is still an ANSWER.

The `searched` list is the case that rules out the lazy fix. A basename
fallback renders every entry as the identical string "jobhunt.json", which is
strictly worse than saying nothing: a reader comparing two candidate locations
sees one. So two DIFFERENT paths must render to two DIFFERENT strings, whatever
form they end up in.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

import pytest

import server
from jobcore import config as jobcore_config
from uplers_server import config as uplers_config_mod
from uplers_server import policy as policy_mod
from uplers_server import profile as profile_mod
from uplers_server import profile_write

from conftest import CONFIDO, put_fixtures

# The shape the brief names: a drive letter followed by a separator.
#
# THE LOOKBEHIND IS LOAD-BEARING. A drive letter is ONE character, and
# without it this matches the "s:/" inside "https://" and reports every
# correct URL in a payload as a leak - measured on this suite, where the
# walker flagged two real platform.uplers.com URLs before it was tightened.
# An instrument that manufactures failures is worse than no instrument,
# because the usual repair is to delete the field that tripped it. The
# control for this line is test_the_leak_regex_does_not_fire_on_an_https_url.
ABSOLUTE_LOCAL = re.compile(r"(?<![A-Za-z])[A-Za-z]:[\\/]")

# Exact anchors for this box, so the sweep still bites on a POSIX runner where
# no drive letter exists. Substring checks against real roots cannot misfire on
# prose the way a general "looks absolute" heuristic would.
REPO_ROOT_TEXT = str(Path(__file__).resolve().parent.parent)
HOME_TEXT = str(Path.home())

#: One backslash, spelled rather than escaped, so a Windows-shaped literal in
#: a control reads the same on a POSIX runner.
B = chr(92)

# The character class above is the one thing in this file a careless rewrite
# can silently destroy. MEASURED on 2026-08-22 elsewhere in this sweep: a
# heredoc collapsed `[\\/]` to `[\/]` - forward slash only - and the detector
# then reported CLEAN on a genuine Windows leak. A detector that cannot fail
# certifies nothing, so the pattern is asserted at IMPORT time and raises
# rather than waiting for a test that would now always pass.
assert ABSOLUTE_LOCAL.search("C:" + B + "Users"), "ABSOLUTE_LOCAL lost its backslash"
assert ABSOLUTE_LOCAL.search("C:/Users"), "ABSOLUTE_LOCAL lost its forward slash"
assert not ABSOLUTE_LOCAL.search("https://x"), "ABSOLUTE_LOCAL lost its lookbehind"


def leaks_in(node, trail="$"):
    """Every (path, string) in a payload that publishes local layout."""
    if isinstance(node, dict):
        for key, value in node.items():
            yield from leaks_in(value, "%s.%s" % (trail, key))
    elif isinstance(node, (list, tuple)):
        for index, value in enumerate(node):
            yield from leaks_in(value, "%s[%d]" % (trail, index))
    elif isinstance(node, str):
        if (ABSOLUTE_LOCAL.search(node)
                or REPO_ROOT_TEXT in node
                or HOME_TEXT in node):
            yield (trail, node)


def spellings(needle):
    """Every spelling a message can carry the path `needle` in.

    TWO, on Windows, and the second one is the whole reason this function
    exists. `OSError.__str__` renders its `filename` through `repr()`, so a
    path that reaches a message through an exception arrives with DOUBLED
    separators - and an exact search for the single-separator form finds
    nothing and reports CLEAN. MEASURED on 2026-08-22: a jobhunt.json that
    existed but could not be read put the full layout into
    `uplers_config().status` and `.notes[0]`, where this detector saw nothing
    and only the drive-letter regex fired.

    That combination is the dangerous one. The regex CANNOT FIRE on the ubuntu
    runner that gates a merge here, and this detector was blind to the repr
    form on every platform - so a real leak had a window where nothing was
    looking at all. Adding the spelling here rather than at each assertion is
    what makes every existing call site inherit it.

    Derived from the needle string unconditionally rather than from `os.sep`,
    so a Windows-shaped literal still yields two forms on a POSIX runner and a
    control means the same thing on both. A POSIX path has no separators to
    double, so the two collapse to one and the tuple is length 1.
    """
    text = str(needle or "")
    if not text:
        return ()
    doubled = text.replace(B, B + B)
    return (text,) if doubled == text else (text, doubled)


def path_hits(node, needle, trail="$"):
    """Every place the EXACT path string `needle` appears. THE PRIMARY DETECTOR.

    `leaks_in` is a SECOND OPINION, and jobcore's CI showed why on 2026-08-22.
    All three of its rules are shape- or anchor-based, and all three are blind
    on the ubuntu runner that actually gates a merge here:

      * the drive-letter regex cannot fire without a drive letter;
      * REPO_ROOT_TEXT is the uplers checkout, and a pytest tmp dir is not
        under it;
      * HOME_TEXT is the user's home, and on the runner `/tmp` is not under
        `/home/runner` either - the very gap that put form 3 into
        jobcore.paths in the first place.

    MEASURED, not reasoned: against the real POSIX-shaped leak
    "/tmp/pytest-of-runner/.../jobhunt.json is not valid JSON", all three rules
    return False and this detector returns True. So on Linux the whole sweep
    would have passed while detecting nothing - certifying the fix on the one
    machine where nobody looks.

    Asserting the absence of the path the FIXTURE ACTUALLY CREATED is
    platform-independent and strictly stronger: it fails on a real leak on
    either OS, and it cannot pass by being unable to see.

    The needle is searched for in every spelling - see :func:`spellings`.
    """
    if isinstance(node, dict):
        for key, value in node.items():
            yield from path_hits(value, needle, "%s.%s" % (trail, key))
    elif isinstance(node, (list, tuple)):
        for index, value in enumerate(node):
            yield from path_hits(value, needle, "%s[%d]" % (trail, index))
    elif isinstance(node, str):
        if any(form in node for form in spellings(needle)):
            yield (trail, node)


def payload_of(result) -> dict:
    """The tool result as the dict a client actually receives."""
    if hasattr(result, "model_dump_json"):
        return json.loads(result.model_dump_json())
    return json.loads(json.dumps(result, default=str))


class TestNoToolResultCarriesALocalPath:

    async def test_no_offline_tool_payload_carries_an_absolute_local_path(
            self, monkeypatch, tmp_path, make_profile, store_factory):
        """One sweep over every payload this suite can build without a network.

        Five surfaces: the profile reader and the config reader (both named by
        the live reproduction), the profile-snapshot writer and the snapshot
        LISTER (both found by grepping for the same shape), and the login
        result. The login case is here to PIN a strip that already happens -
        server.uplers_login() drops `profile_dir` from auth's dict - so that
        removing that filter later fails here instead of quietly re-opening the
        leak.
        """
        make_profile()
        monkeypatch.setattr(server, "_open_store", store_factory)
        put_fixtures(store_factory(), [CONFIDO])
        config_file = tmp_path / "jobhunt.json"
        config_file.write_text(json.dumps({"scoring": {}}), encoding="utf-8")
        monkeypatch.setenv("JOBHUNT_CONFIG", str(config_file))
        policy_mod.invalidate()

        snapshots = tmp_path / "snaps"
        snapshots.mkdir()
        monkeypatch.setattr(profile_write, "snapshots_dir", lambda: snapshots)

        from uplers_server.session import SessionStore

        session_file = tmp_path / "session.json"
        monkeypatch.setattr(server, "_session_store",
                            lambda: SessionStore(session_file))

        async def fake_login(store, wait_seconds=180):
            return {
                "authenticated": True,
                "method": "browser",
                "profile_dir": str(tmp_path / "browser_profile"),
                "elapsed_seconds": 1.0,
                "checks_run": 1,
                "checked_against": "talent/hr/profile",
                "session": store.describe(),
            }

        monkeypatch.setattr(server.auth_mod, "login_via_browser", fake_login)

        payloads = {
            "uplers_get_profile": payload_of(await server.uplers_get_profile()),
            "uplers_config": payload_of(await server.uplers_config()),
            "uplers_login": payload_of(await server.uplers_login()),
            "profile_write.write_snapshot": payload_of(
                profile_write.write_snapshot(
                    {"talent_details": {"skills": []}, "masters": {"skills": []}},
                    label="hygiene",
                )
            ),
            "uplers_list_profile_snapshots": payload_of(
                await server.uplers_list_profile_snapshots()
            ),
            # Carries `url` = "https://platform.uplers.com/...". Here to keep the
            # SWEEP honest in the other direction: an instrument that flags a
            # correct URL manufactures failures, and the fix for a manufactured
            # failure is usually to delete the field that triggered it.
            "uplers_get_opportunity": payload_of(
                await server.uplers_get_opportunity(CONFIDO)
            ),
        }

        # PRIMARY: the exact directory this test created must appear nowhere.
        # Platform-independent, unlike everything in `leaks_in`.
        primary = [
            "%s %s = %r" % (tool, trail, text)
            for tool, payload in payloads.items()
            for trail, text in path_hits(payload, str(tmp_path))
        ]
        assert primary == [], primary
        # SECOND OPINION: shape-based, and blind on the Linux runner.
        found = [
            "%s %s = %r" % (tool, trail, text)
            for tool, payload in payloads.items()
            for trail, text in leaks_in(payload)
        ]
        assert found == [], found

    async def test_a_broken_config_file_does_not_leak_its_path(
            self, monkeypatch, tmp_path, make_profile):
        """The error path leaks too, and it reaches further than uplers_config.

        Not on the brief's list; found by reading jobcore. When a jobhunt.json
        cannot be parsed, jobcore composes `config_error` as an f-string with
        the ABSOLUTE path already inside it - "{path} is not valid JSON: ...".
        That string is then interpolated twice over: into `ConfigReport.status`
        via `config_status`, and into `Bound.notes()`, which every scoring tool
        appends to its own notes. So a single unparseable file publishes the
        layout from tools that never render a path at all.

        Relativising a composed sentence needs the raw path substituted inside
        it, which is why this is a separate assertion from the plain fields.
        """
        make_profile()
        config_file = tmp_path / "jobhunt.json"
        config_file.write_text("{ this is not json", encoding="utf-8")
        monkeypatch.setenv("JOBHUNT_CONFIG", str(config_file))
        policy_mod.invalidate()

        report = await server.uplers_config()
        profile = await server.uplers_get_profile()

        # the error must still SAY what went wrong and which file
        assert "not valid JSON" in (report.status or ""), report.status
        assert "jobhunt.json" in (report.status or ""), report.status
        # ... without the layout, here and in the notes of a tool that renders
        # no path of its own
        primary = [
            "uplers_config %s = %r" % (trail, text)
            for trail, text in path_hits(payload_of(report), str(tmp_path))
        ] + [
            "uplers_get_profile %s = %r" % (trail, text)
            for trail, text in path_hits(payload_of(profile), str(tmp_path))
        ]
        assert primary == [], primary
        found = [
            "uplers_config %s = %r" % (trail, text)
            for trail, text in leaks_in(payload_of(report))
        ] + [
            "uplers_get_profile %s = %r" % (trail, text)
            for trail, text in leaks_in(payload_of(profile))
        ]
        assert found == [], found

    async def test_a_missing_config_relativises_every_searched_path(
            self, monkeypatch, tmp_path, make_profile):
        """`searched` is the "where is the file even" answer. It must not leak."""
        make_profile()
        monkeypatch.setenv("JOBHUNT_CONFIG", str(tmp_path / "absent.json"))
        policy_mod.invalidate()

        report = await server.uplers_config()

        assert report.searched, "a missing file must still name what it tried"
        primary = list(path_hits(payload_of(report), str(tmp_path)))
        assert primary == [], primary
        found = [
            (trail, text)
            for trail, text in leaks_in(payload_of(report))
        ]
        assert found == [], found


class TestTheRenderedPathIsStillAnAnswer:

    def test_two_different_searched_paths_do_not_render_alike(self, tmp_path):
        """The assertion that rules out a basename fallback.

        Three pairs, because the collapse is only visible when two paths share
        a filename and differ only above it: under the anchor, under home, and
        under the filesystem root.

        EVERY ROOT IS DERIVED, NEVER SPELLED. The first version of this test
        hardcoded ``Z:/opt/one/jobhunt.json`` and broke uplers CI on both Linux
        jobs (run 32558985977). That string is an ABSOLUTE path on Windows and a
        RELATIVE one on POSIX - `Path("Z:/opt/x").parts` on Linux starts with
        the literal component ``Z:`` and there is no anchor - so `display_path`
        correctly passed the relative path through untouched and the sweep then
        found ``Z:/`` inside it. The renderer was right; the fixture meant two
        different things on two platforms. `tmp_path.anchor` is the drive root
        here and ``/`` on the runner, so the third pair is absolute on both.

        And the assertion is on the PROPERTY, not on which of the three forms
        fires. Which one fires legitimately depends on how deep the checkout
        sits - on this box the third pair lands on the tail form, on a runner it
        can land on the relative form - but "two distinct paths stay distinct,
        and neither collapses to the bare basename" must hold everywhere.
        """
        root = Path(uplers_config_mod.REPO_ROOT)
        filesystem_root = Path(tmp_path.anchor)
        pairs = (
            (root / "one" / "jobhunt.json", root / "two" / "jobhunt.json"),
            (Path.home() / "one" / "jobhunt.json",
             Path.home() / "two" / "jobhunt.json"),
            (filesystem_root / "opt" / "one" / "jobhunt.json",
             filesystem_root / "opt" / "two" / "jobhunt.json"),
        )
        for left, right in pairs:
            assert left.is_absolute(), left      # the fixture's own precondition
            assert right.is_absolute(), right
            rendered_left = policy_mod.display_path(str(left))
            rendered_right = policy_mod.display_path(str(right))
            assert rendered_left != rendered_right, (left, right, rendered_left)
            assert rendered_left != "jobhunt.json", rendered_left
            # PRIMARY: platform-independent - the raw path must not survive.
            assert str(left) not in rendered_left, rendered_left
            assert str(right) not in rendered_right, rendered_right
            assert not ABSOLUTE_LOCAL.search(rendered_left), rendered_left
            assert not ABSOLUTE_LOCAL.search(rendered_right), rendered_right

    def test_the_shared_config_two_levels_up_renders_relative(self):
        """The real layout: config/jobhunt.json sits two levels above the checkout.

        This is the exact string the live leak produced in full, so it is the
        one worth pinning character for character.
        """
        root = Path(uplers_config_mod.REPO_ROOT)
        shared = root.parent.parent / "config" / "jobhunt.json"

        assert policy_mod.display_path(str(shared)) == "../../config/jobhunt.json"

    async def test_the_config_source_is_relativised_and_still_names_jobhunt_json(
            self, monkeypatch, tmp_path, make_profile):
        """BOTH halves of the ruling, in one test, because either alone passes.

        Asserting only "no leak" is satisfied by deleting the field; asserting
        only "still names jobhunt.json" is satisfied by the leaking code this
        replaces. The ruling is the conjunction - relativise, do not delete -
        so the conjunction is what gets pinned.
        """
        make_profile()
        config_file = tmp_path / "jobhunt.json"
        config_file.write_text(json.dumps({"scoring": {}}), encoding="utf-8")
        monkeypatch.setenv("JOBHUNT_CONFIG", str(config_file))
        policy_mod.invalidate()

        report = await server.uplers_config()

        # still an answer
        assert report.source is not None
        assert report.source.endswith("jobhunt.json"), report.source
        assert "loaded from" in (report.status or ""), report.status
        assert report.status.endswith("jobhunt.json"), report.status
        # and not this machine's layout
        assert str(tmp_path) not in report.source, report.source
        assert str(tmp_path) not in report.status, report.status
        assert not ABSOLUTE_LOCAL.search(report.source), report.source
        assert HOME_TEXT not in report.source, report.source
        assert not ABSOLUTE_LOCAL.search(report.status), report.status

    async def test_the_profile_path_still_names_profile_json(self, make_profile,
                                                             isolated_profile):
        """Same pairing on the other reproduced field."""
        make_profile()

        result = await server.uplers_get_profile()

        assert result.path is not None
        assert result.path.endswith("profile.json"), result.path
        # PRIMARY, and the only half of this that can fail on the Linux runner.
        assert str(isolated_profile.parent) not in result.path, result.path
        assert not ABSOLUTE_LOCAL.search(result.path), result.path


class TestTheWriteResultAndTheInstrumentItself:
    """Two things the first pass missed, both found by reading jobcore 0f557eb.

    `uplers_config(write_candidate=True)` returns jobcore's `apply_patch` dict
    STRAIGHT THROUGH as `ConfigReport.write`, and that dict carries paths in
    three places the earlier sweep never looked at: `path` on success,
    `ledger_error`, and `detail` on a lock conflict. The last two are the case
    that motivated jobcore's `Loaded.known_paths` including PARENT DIRECTORIES
    - the ledger and the lock file are named from the config's directory and
    neither equals `source`, so a substitution keyed only on source+searched
    (which is what this server shipped in c65f9ef) cannot touch them.
    """

    async def test_a_successful_write_does_not_leak_the_config_path(
            self, monkeypatch, tmp_path, make_profile):
        """The HAPPY path leaks: apply_patch's ok-return carries "path": str(target)."""
        make_profile()
        config_file = tmp_path / "jobhunt.json"
        config_file.write_text(json.dumps({"revision": 1}), encoding="utf-8")
        monkeypatch.setenv("JOBHUNT_CONFIG", str(config_file))
        policy_mod.invalidate()

        report = await server.uplers_config(write_candidate=True,
                                            allow_score_raising=True)

        assert report.write.get("status") == "ok", report.write
        primary = list(path_hits(payload_of(report), str(tmp_path)))
        assert primary == [], primary
        found = [
            "%s = %r" % (trail, text)
            for trail, text in leaks_in(payload_of(report))
        ]
        assert found == [], found

    async def test_a_lock_conflict_does_not_leak_the_lock_file(
            self, monkeypatch, tmp_path, make_profile):
        """The parent-directory case, with jobcore's OWN message text.

        The lock file lives beside the config and never equals `source`, so this
        is the exact case `known_paths` adds parents for. The detail string is
        not invented here - it is `str(ConfigLockedError(...))`, jobcore's real
        exception, so the test cannot drift from the message it guards.
        """
        make_profile()
        config_file = tmp_path / "jobhunt.json"
        config_file.write_text(json.dumps({"revision": 1}), encoding="utf-8")
        monkeypatch.setenv("JOBHUNT_CONFIG", str(config_file))
        policy_mod.invalidate()

        lock_file = config_file.parent / "jobhunt.lock"
        locked = jobcore_config.ConfigLockedError(4242, lock_file)

        def refuse(*args, **kwargs):
            return {"status": "error", "detail": str(locked), "holder_pid": 4242}

        monkeypatch.setattr(jobcore_config, "apply_patch", refuse)

        report = await server.uplers_config(write_candidate=True)

        # still an answer: it must say a lock, and which pid
        assert "4242" in report.write["detail"]
        assert "jobhunt.lock" in report.write["detail"]
        primary = list(path_hits(payload_of(report), str(tmp_path)))
        assert primary == [], primary
        found = [
            "%s = %r" % (trail, text)
            for trail, text in leaks_in(payload_of(report))
        ]
        assert found == [], found

    def test_the_leak_regex_does_not_fire_on_an_https_url(self):
        """CONTROL for this file's own instrument, not for the server.

        `[A-Za-z]:[\\/]` matches the "s:/" inside "https://". Every uplers
        opportunity payload carries a platform.uplers.com URL, so the loose
        form turns a correct field into a reported leak - and the usual repair
        for a manufactured failure is to delete the field that tripped it.
        A drive letter is ONE character; the lookbehind is what says so.
        """
        assert not ABSOLUTE_LOCAL.search("https://platform.uplers.com/talent/x")
        assert not ABSOLUTE_LOCAL.search("http://localhost:8765/a")
        # and it must still catch what it is for
        assert ABSOLUTE_LOCAL.search(r"D:\Sundeep\projects\job-hunting")
        assert ABSOLUTE_LOCAL.search("C:/Users/Dell/AppData")


class TestTheInstrumentCanActuallyFail:
    """A check that cannot fail certifies nothing. These are the controls.

    Every assertion in this file says a leak is ABSENT. That shape is only
    trustworthy if the detector behind it demonstrably fires when a leak is
    PRESENT - and jobcore's CI proved on 2026-08-22 that the drive-letter form
    does not, on the exact platform that gates a merge for this repo.
    """

    def test_the_drive_letter_rule_is_blind_to_a_posix_leak(self):
        """The measurement that demotes `leaks_in` to a second opinion.

        This is what a leaked config path looks like on ubuntu-latest. Not one
        of the three rules in `leaks_in` can see it, and each is blind for its
        own reason - no drive letter, not under the checkout, not under home.
        """
        posix_leak = {
            "status": "/tmp/pytest-of-runner/pytest-0/test_x0/jobhunt.json"
                      " is not valid JSON"
        }

        assert list(leaks_in(posix_leak)) == [], (
            "if this ever starts failing, leaks_in grew a rule that sees POSIX "
            "paths and this control needs rewriting, not deleting"
        )
        assert list(path_hits(posix_leak, "/tmp/pytest-of-runner/pytest-0/test_x0"))

    def test_the_primary_detector_fires_on_a_real_leak(self, tmp_path):
        """Falsifiability for `path_hits`, asserted the same way on both platforms.

        The `leaks_in` half deliberately uses a Windows-shaped LITERAL rather
        than this run's tmp_path. A literal makes the assertion deterministic:
        `leaks_in` is a pure function of the string, so it means the same thing
        on the runner as it does here. Handing it a real tmp_path instead would
        assert something true on Windows and FALSE on ubuntu, where
        /tmp/pytest-of-runner/... trips none of its three rules - the exact
        trap this class exists to document.
        """
        leaky = {"path": str(tmp_path / "data" / "profile.json")}
        assert list(path_hits(leaky, str(tmp_path)))

        windows_shaped = {"path": "D:" + B + "Sundeep" + B + "x" + B + "profile.json"}
        assert list(leaks_in(windows_shaped))

    def test_the_primary_detector_passes_a_relativised_payload(self, tmp_path):
        """And it must not fire on the rendered form, or every fix looks broken."""
        clean = {"path": "data/profile.json",
                 "source": "../../config/jobhunt.json",
                 "url": "https://platform.uplers.com/talent/x"}

        assert list(path_hits(clean, str(tmp_path))) == []
        assert list(leaks_in(clean)) == []


class TestTheReprSpellingOfAPath:
    """An OSError spells its filename through repr(), and the scrubber missed it.

    MEASURED on this box on 2026-08-22, offline, against the committed tree at
    15984d1. A jobhunt.json that EXISTS but cannot be read produced this
    `uplers_config().status` of the form::

        error: cannot read ~/AppData/Local/Temp/.../config/jobhunt.json:
        [Errno 13] Permission denied: 'C: Users Dell ... jobhunt.json'

    where every gap in that second half is a DOUBLED separator - two literal
    characters in the string, not this docstring escaping one. They are shown
    as gaps because a docstring cannot print them literally without escaping
    them again, which is exactly the confusion this defect lives inside.

    ONE sentence, two halves, OPPOSITE VERDICTS. The ``{path}`` half was
    correctly relativised - the substitution machinery ran and worked. The
    ``{exc}`` half is THE SAME PATH, spelled the way ``repr()`` spells it,
    because ``OSError.__str__`` renders its ``filename`` through ``repr()``.
    Every exact-substring scrubber in this family searches for the
    single-separator form, finds nothing, and passes the payload through as
    clean. Measured verdicts on that payload, before the fix::

        PRIMARY  (exact single form) : CLEAN
        REPR     (exact doubled form): ['.status', '.notes[0]']
        2nd OPIN (drive-letter regex): ['.status', '.notes[0]']

    ``.notes[0]`` matters as much as ``.status``: ``Bound.notes()`` is appended
    by every scoring tool, so this reaches results that render no path field
    at all.

    THE FIX IS ONE MORE SPELLING OF THE SAME NEEDLE, never a path-shaped-text
    hunt. A heuristic scrubber eventually eats a platform.uplers.com URL and
    does more damage than the leak it was written for - the failure this
    file's own ``ABSOLUTE_LOCAL`` control already documents. On POSIX the two
    spellings are IDENTICAL, so the extra needle adds nothing there and costs
    nothing.
    """

    def test_an_oserror_spells_its_filename_with_doubled_backslashes(self, tmp_path):
        """The MECHANISM, pinned, so the extra needles can be retired knowingly.

        Declared plainly: this one does NOT go red before the fix. It
        characterises CPython rather than this server, and it is the premise
        every needle below rests on. The ``os.sep`` guard is what makes it fail
        LOUDLY if a future Python stops rendering ``filename`` through
        ``repr()`` - at which point the extra spelling becomes dead weight and
        can be dropped on purpose instead of by accident.
        """
        target = tmp_path / "config" / "jobhunt.json"
        exc = OSError(13, "Permission denied", str(target))
        message = str(exc)

        assert "Permission denied" in message, message
        # repr(), not str(): the filename arrives QUOTED and escaped.
        assert repr(str(target)) in message, message
        if os.sep == B:
            # The blind spot itself, stated as a measurement, not a comment.
            assert str(target) not in message, message
            assert str(target).replace(B, B + B) in message, message

    async def test_an_unreadable_config_does_not_leak_the_repr_spelling(
            self, monkeypatch, tmp_path, make_profile):
        """END TO END: a real OSError, from a real read, reaching a real result.

        Nothing hand-built. ``OSError(13, "Permission denied", str(path))`` is
        the object CPython itself constructs, raised from the one call jobcore
        makes - ``path.read_bytes()`` in ``config.current`` - so the sentence
        under test is jobcore's own ``f"cannot read {path}: {exc}"`` and cannot
        drift from it.

        Asserted three ways, because each detector is blind somewhere: the
        single-form needle (what the scrubber searched for), the doubled-form
        needle (what the message actually carries), and the drive-letter regex
        (which sees the shape but cannot fire on the Linux runner at all).
        """
        make_profile()
        config_file = tmp_path / "jobhunt.json"
        config_file.write_text(json.dumps({"revision": 1}), encoding="utf-8")
        monkeypatch.setenv("JOBHUNT_CONFIG", str(config_file))

        readable = Path.read_bytes

        def refuse(self):
            if self.name == "jobhunt.json":
                raise OSError(13, "Permission denied", str(self))
            return readable(self)

        monkeypatch.setattr(Path, "read_bytes", refuse)
        policy_mod.invalidate()

        report = await server.uplers_config()
        profile = await server.uplers_get_profile()
        payloads = {
            "uplers_config": payload_of(report),
            # renders no path field of its own, and still carried the leak
            # through Bound.notes()
            "uplers_get_profile": payload_of(profile),
        }

        # still an answer: it must say what went wrong and name the file
        assert "cannot read" in (report.status or ""), report.status
        assert "jobhunt.json" in (report.status or ""), report.status

        raw = str(tmp_path)
        doubled = raw.replace(B, B + B)
        single = [
            "%s %s = %r" % (tool, trail, text)
            for tool, payload in payloads.items()
            for trail, text in path_hits(payload, raw)
        ]
        assert single == [], single
        repr_form = [
            "%s %s = %r" % (tool, trail, text)
            for tool, payload in payloads.items()
            for trail, text in path_hits(payload, doubled)
        ]
        assert repr_form == [], repr_form
        regex = [
            "%s %s = %r" % (tool, trail, text)
            for tool, payload in payloads.items()
            for trail, text in leaks_in(payload)
        ]
        assert regex == [], regex

    def test_the_two_detectors_disagree_on_the_repr_spelling(self):
        """CONTROL. The disagreement IS the finding, so it is measured, not noted.

        A Windows-shaped LITERAL, never this run's tmp_path, so every assertion
        means the same thing on the ubuntu runner: both detectors are pure
        functions of the string, and feeding them a real POSIX tmp_path would
        assert something true here and FALSE there - the trap this file's
        instrument-control class already documents.
        """
        single = B.join(("C:", "Users", "Dell", "cfg", "jobhunt.json"))
        leak = {"status": "cannot read x: [Errno 13] Permission denied: %r" % single}

        # 1. The needle every scrubber in this family searched for is GENUINELY
        #    ABSENT from the leaking string. Not a near miss - not present.
        assert single not in leak["status"], leak["status"]
        # 2. The drive-letter regex does see it. Two detectors, one payload,
        #    opposite verdicts - and on Linux the one that sees it cannot fire,
        #    so a real leak has a window where NOTHING is looking.
        assert ABSOLUTE_LOCAL.search(leak["status"]), leak["status"]
        assert list(leaks_in(leak)), leak
        # 3. With the repr spelling added as a needle, the primary agrees again
        #    - on both platforms, which the regex never could.
        assert list(path_hits(leak, single)), leak["status"]

    def test_the_repr_needle_catches_a_planted_leak(self, tmp_path):
        """CONTROL. Falsifiability for the added spelling, identical on both OSes.

        The needle is a Windows-shaped LITERAL so ``path_hits`` derives two
        DISTINCT spellings from it even on a POSIX runner; the tmp_path pair
        keeps the control honest about the detector's ordinary use, and the
        last assertion keeps it honest in the other direction - an instrument
        that fires on a correctly rendered payload manufactures failures, and
        the usual repair for one of those is to delete the field that tripped it.
        """
        single = B.join(("D:", "Sundeep", "projects", "data", "profile.json"))
        planted = {"detail": "[Errno 13] Permission denied: "
                             + single.replace(B, B + B)}

        assert single not in planted["detail"], planted
        assert list(path_hits(planted, single)), planted
        # the ordinary single-spelling case must keep working
        assert list(path_hits({"path": str(tmp_path / "x.json")}, str(tmp_path)))
        # and neither spelling may fire on the rendered form
        assert list(path_hits({"path": "data/profile.json"}, single)) == []

    async def test_an_unparseable_config_does_not_report_as_loaded(
            self, monkeypatch, tmp_path, make_profile):
        """The negative pin ``config_status`` never had. A corrected finding.

        The false-success found on the sibling server is NOT present here -
        MEASURED on all three failure branches, uplers reports honestly. But
        nothing pinned it: the only assertion on ``status`` anywhere was the
        HEALTHY case (``"loaded from" in report.status``), which a false
        success passes without noticing.

        ``source`` is deliberately NOT asserted to be None, because it is not:
        measured on all three branches it still NAMES the file, correctly, and
        pinning a value the code does not produce would be pinning a wish.
        """
        make_profile()
        config_file = tmp_path / "jobhunt.json"
        cases = (
            ("malformed json", b'{"revision": 1,}'),
            ("json but not an object", b"[1, 2, 3]"),
            ("undecodable bytes", b'{"a": "\xe9"}'),
        )
        for label, raw in cases:
            config_file.write_bytes(raw)
            monkeypatch.setenv("JOBHUNT_CONFIG", str(config_file))
            policy_mod.invalidate()

            report = await server.uplers_config()

            status = report.status or ""
            assert "loaded from" not in status, (label, status)
            assert status.startswith("error:"), (label, status)
            # and it is still an ANSWER - the pin must not be satisfiable by
            # emptying the field
            assert "jobhunt.json" in status, (label, status)

    async def test_an_unreadable_profile_does_not_leak_its_path(
            self, monkeypatch, make_profile, isolated_profile):
        """The SECOND, different leak: profile.load() names the file twice over.

        ``target`` is ``profile_path()`` - not a config path, so it is not in
        ``Loaded.known_paths`` at all and no existing substitution touches
        either half. MEASURED: the ``{target}`` half leaks the single spelling
        and the ``{exc}`` half leaks the doubled one, from the same sentence.
        It reaches a caller through ``uplers_config(write_candidate=True)``,
        which re-raises ``str(exc)``.

        The reader function is exercised against a file on disk, which is this
        repo's established practice; no MCP tool is called.
        """
        make_profile()
        readable = Path.open

        def refuse(self, *args, **kwargs):
            if self.name == "profile.json":
                raise OSError(13, "Permission denied", str(self))
            return readable(self, *args, **kwargs)

        monkeypatch.setattr(Path, "open", refuse)

        with pytest.raises(profile_mod.ProfileError) as caught:
            profile_mod.load(path=isolated_profile)

        message = str(caught.value)
        # still an answer
        assert "profile.json" in message, message
        assert "could not be read as JSON" in message, message
        # and neither spelling of the layout, by either detector
        found = list(path_hits({"message": message},
                               str(isolated_profile.parent)))
        assert found == [], found
        second = list(leaks_in({"message": message}))
        assert second == [], second

    def test_an_unreadable_snapshot_does_not_leak_its_path(
            self, monkeypatch, tmp_path):
        """``{path.name}`` was already safe; the ``({exc})`` beside it was not.

        The same defect one file over, and the reason the fix is a SHARED
        primitive rather than four local repairs: three of these four sites
        compose a message around an exception this server never looks inside.
        """
        snapshots = tmp_path / "snaps"
        snapshots.mkdir()
        snapshot = snapshots / "1787000000-x.json"
        snapshot.write_text(json.dumps({"skills": ["Node.js"]}), encoding="utf-8")
        monkeypatch.setattr(profile_write, "snapshots_dir", lambda: snapshots)

        readable = Path.read_text

        def refuse(self, *args, **kwargs):
            if self.name == snapshot.name:
                raise OSError(13, "Permission denied", str(self))
            return readable(self, *args, **kwargs)

        monkeypatch.setattr(Path, "read_text", refuse)

        with pytest.raises(profile_write.WriteRefused) as caught:
            profile_write.load_snapshot("1787000000-x")

        message = str(caught.value)
        # still an answer: it must name WHICH snapshot
        assert "1787000000-x.json" in message, message
        found = list(path_hits({"message": message}, str(tmp_path)))
        assert found == [], found
        second = list(leaks_in({"message": message}))
        assert second == [], second


# =====================================================================
# The FOURTH branch, where the path is not a string but a LIST
# =====================================================================
# ``no_config_file`` returns ``searched`` as a list of absolute paths beside a
# ``detail`` string composed from the same path. The string half was already
# rendered; the list half was not, because the walk stopped at a flat dict's
# string values - this server's own explicit, documented decision, which the
# naukri server then mirrored.
#
# ``searched`` is the field whose entire job is answering "why is my config
# file not being read", and THIS SERVER HAS NO BOUNDARY SCRUBBER - grep for
# ``scrub_result`` across ``uplers_server/`` and ``server.py`` returns nothing -
# so the raw absolute paths reached the wire on every platform, through
# ``uplers_config(write_candidate=True).write``.
#
# MEASURED on 2026-08-22, this box, before any edit::
#
#     "detail":   "JOBHUNT_CONFIG=~/AppData/.../does-not-exist/jobhunt.json
#                  points at no file"                          <- rendered
#     "searched": ["C:\\Users\\Dell\\AppData\\...\\jobhunt.json"]   <- raw
#     PRIMARY (exact) ['.searched[0]']   2nd OPIN (regex) ['.searched[0]']
#
# The identical measurement was taken on the naukri server, whose scrubber
# "saves" the field only by collapsing every entry to the identical string
# ``jobhunt.json``. The fix is one shape in both repos; see
# ``naukri_server/policy.py``.


def _one_level_only(payload, loaded):
    """THE REJECTED ALTERNATIVE, kept executable so the choice is a measurement.

    "Walk one level" means: render a string value, and render the string
    ELEMENTS of a value that is a list. It fixes ``searched`` and it does not
    reach ``changed``, whose values are ``{key: [old, new]}`` one level further
    down. Full recursion was chosen instead; this exists so that choice is
    pinned by a test that FAILS on the shallower rule rather than by a comment.
    """
    out = {}
    for key, value in payload.items():
        if isinstance(value, list):
            out[key] = [policy_mod.relativise_known_paths(item, loaded)
                        for item in value]
        else:
            out[key] = policy_mod.relativise_known_paths(value, loaded)
    return out


def _bind_missing_config(monkeypatch, where: Path) -> Path:
    """Bind a config path that DOES NOT EXIST, and prove nothing resolves.

    The safety gate matters even though this branch writes nothing: the file
    ``apply_patch`` would otherwise resolve to is shared by every server in
    this family, and a test that accidentally found a real one would stop
    exercising the branch under test and start writing it.
    """
    where.mkdir(parents=True, exist_ok=True)
    cfg = where / "jobhunt.json"
    assert not cfg.exists(), cfg
    monkeypatch.setenv("JOBHUNT_CONFIG", str(cfg))
    policy_mod.invalidate()

    located = jobcore_config.locate(Path(profile_mod.__file__))
    assert not located.found, (
        "REFUSING TO CONTINUE: a real config file resolved at %r"
        % (getattr(located, "path", None),)
    )
    assert located.searched, "locate() searched nothing; the branch is not armed"
    for entry in located.searched:
        assert str(where) in str(entry), (
            "REFUSING TO CONTINUE: locate() names %r, outside the temp dir %r"
            % (entry, where)
        )
    return cfg


def _bind_real_config(monkeypatch, tmp_path: Path) -> Path:
    """A throwaway jobhunt.json that EXISTS, so ``known_paths`` is populated."""
    cfg = tmp_path / "config" / "jobhunt.json"
    cfg.parent.mkdir(parents=True, exist_ok=True)
    cfg.write_text(json.dumps({"config_version": 1, "revision": 1}),
                   encoding="utf-8")
    monkeypatch.setenv("JOBHUNT_CONFIG", str(cfg))
    policy_mod.invalidate()
    return cfg


class TestTheseListAssertionsCanFail:
    """Controls. Every assertion in the next class says a path is ABSENT."""

    def test_raw_jobcore_really_does_return_the_searched_list_absolute(
            self, monkeypatch, tmp_path):
        """CONTROL for the branch, and it runs on every OS.

        If jobcore ever rendered ``searched`` itself, the leak test below would
        pass while proving nothing about this server.
        """
        missing = _bind_missing_config(monkeypatch, tmp_path / "gone")
        raw = jobcore_config.apply_patch(
            {"candidate": {"years_experience": 5}},
            start=missing.parent, actor="test",
            allowed_sections=("candidate",))

        assert raw["status"] == "no_config_file", raw
        assert raw["searched"], "the branch returned no searched list at all"
        assert any(str(tmp_path) in entry for entry in raw["searched"]), (
            "jobcore no longer bakes the absolute path into `searched`; the "
            "absence assertions below prove nothing"
        )

    def test_the_primary_detector_sees_a_path_inside_a_list(self, tmp_path):
        """CONTROL for the instrument on the SHAPE this slice is about.

        ``path_hits`` was only ever shown firing on a path in a string FIELD.
        A detector that walked dicts but not lists would report CLEAN on
        exactly the payload below and certify the leak as fixed.
        """
        leaking = {"status": "no_config_file",
                   "searched": [str(tmp_path / "gone" / "jobhunt.json")]}

        assert [trail for trail, _ in path_hits(leaking, str(tmp_path))] == [
            "$.searched[0]"
        ]

    def test_a_one_level_walk_leaves_the_changed_payload_absolute(
            self, monkeypatch, tmp_path):
        """CONTROL that turns the depth choice into a measurement.

        This is the shallower rule this slice rejected, run against the payload
        that separates the two. It renders ``searched`` and it does NOT render
        the path sitting inside ``changed``, which is where jobcore puts
        ``{key: [old, new]}`` pairs of arbitrary config values. If this ever
        stops failing to render, one level became sufficient and the recursion
        can be narrowed.
        """
        cfg = _bind_real_config(monkeypatch, tmp_path)
        ld = policy_mod.snapshot()
        payload = {"searched": [str(cfg)],
                   "changed": {"servers.uplers.export_dir": [str(cfg), None]}}

        shallow = _one_level_only(payload, ld)

        assert list(path_hits(shallow["searched"], str(tmp_path))) == [], (
            "the one-level rule cannot even render `searched`; this control is "
            "measuring something other than depth"
        )
        assert list(path_hits(shallow["changed"], str(tmp_path))) != [], (
            "the one-level rule now reaches `changed` too, so the recursion "
            "chosen here is wider than it needs to be"
        )


class TestTheSearchedListIsRendered:

    async def test_the_no_config_file_branch_does_not_leak_the_searched_list(
            self, monkeypatch, tmp_path, make_profile):
        """THE LEAK, at the tool. A list of paths beside a string that was fine."""
        make_profile()
        _bind_missing_config(monkeypatch, tmp_path / "gone")

        report = await server.uplers_config(write_candidate=True)

        assert report.write.get("status") == "no_config_file", report.write
        assert report.write["searched"], report.write
        primary = [
            "%s = %r" % (trail, text)
            for trail, text in path_hits(payload_of(report), str(tmp_path))
        ]
        assert primary == [], primary
        found = [
            "%s = %r" % (trail, text)
            for trail, text in leaks_in(payload_of(report))
        ]
        assert found == [], found

    async def test_two_missing_candidates_do_not_render_alike(
            self, monkeypatch, tmp_path, make_profile):
        """STILL AN ANSWER, on the field whose whole job is being one.

        A basename fallback renders every entry of this list as the identical
        string ``jobhunt.json`` - which is what the sibling server's boundary
        scrubber does to it today - and under that a reader comparing two
        candidate locations sees one. A fix that reproduces the collapse must
        fail here.
        """
        make_profile()

        alpha = _bind_missing_config(monkeypatch, tmp_path / "alpha")
        one = (await server.uplers_config(write_candidate=True)).write
        assert one.get("status") == "no_config_file", one

        beta = _bind_missing_config(monkeypatch, tmp_path / "beta")
        two = (await server.uplers_config(write_candidate=True)).write
        assert two.get("status") == "no_config_file", two

        # CONTROL: the two candidates really are indistinguishable by basename.
        assert alpha.name == beta.name == "jobhunt.json"
        assert one["searched"] and two["searched"], (one, two)
        assert one["searched"] != two["searched"], (
            "two different candidate paths render identically as %r"
            % (one["searched"],)
        )
        for entry in one["searched"]:
            assert entry.endswith("alpha/jobhunt.json"), entry
        for entry in two["searched"]:
            assert entry.endswith("beta/jobhunt.json"), entry


class TestTheWalkGoesAllTheWayDown:
    """FULL RECURSION, chosen over one level, pinned here rather than described.

    ``changed`` on the SUCCESS payload is ``{key: [old, new]}`` over arbitrary
    config values, so a path can sit two containers below the top. Depth costs
    nothing in safety because ``relativise_known`` only ever replaces a string
    the snapshot ALREADY KNOWS is a path - the exactness, not the depth, is
    what keeps a platform.uplers.com URL out of reach. A depth limit would be
    an arbitrary line that the next jobcore field crosses, and this leak is
    what that line looks like when it is crossed.
    """

    def test_a_known_path_nested_two_containers_deep_is_rendered(
            self, monkeypatch, tmp_path):
        cfg = _bind_real_config(monkeypatch, tmp_path)
        ld = policy_mod.snapshot()
        payload = {"status": "ok",
                   "changed": {"servers.uplers.export_dir": [str(cfg), None]}}

        rendered = policy_mod.relativise_mapping(payload, ld)

        assert list(path_hits(rendered, str(tmp_path))) == [], rendered
        # STILL AN ANSWER, and still the same shape.
        old, new = rendered["changed"]["servers.uplers.export_dir"]
        assert new is None
        assert old.endswith("config/jobhunt.json"), old

    def test_a_tuple_stays_a_tuple_and_a_list_stays_a_list(
            self, monkeypatch, tmp_path):
        """Types survive the walk, because a caller compares them.

        ``Loaded.searched`` is a tuple and jobcore's payload lists are lists;
        rebuilding either as the other would break equality for every consumer
        that round-trips this dict.
        """
        _bind_real_config(monkeypatch, tmp_path)
        ld = policy_mod.snapshot()

        out = policy_mod.relativise_mapping(
            {"a": [1, 2], "b": (1, 2), "c": {"d": [3]}}, ld)

        assert isinstance(out["a"], list) and out["a"] == [1, 2]
        assert isinstance(out["b"], tuple) and out["b"] == (1, 2)
        assert out["c"] == {"d": [3]}
        # and the "a mapping, or nothing" contract at the top is unchanged
        assert policy_mod.relativise_mapping("not a dict", ld) == "not a dict"

    def test_a_url_and_an_api_route_inside_a_list_survive(
            self, monkeypatch, tmp_path):
        """The exactness that makes walking into a list safe at all.

        A loose "looks like a path" rule flagged two CORRECT
        platform.uplers.com URLs in a real payload on 2026-08-22. Walking
        deeper multiplies the number of strings a heuristic would get to be
        wrong about, which is exactly why the substitution must stay exact -
        and why this control lives next to the depth increase.
        """
        _bind_real_config(monkeypatch, tmp_path)
        ld = policy_mod.snapshot()
        payload = {"searched": [
            "https://platform.uplers.com/talent/hr/profile",
            "GET talent/hr/opportunity returned 500",
            "http://localhost:8765/preview",
        ]}

        assert policy_mod.relativise_mapping(payload, ld) == payload

    def test_but_a_known_path_in_that_same_list_is_replaced(
            self, monkeypatch, tmp_path):
        """CONTROL for the test above: the deep walk is not simply inert."""
        cfg = _bind_real_config(monkeypatch, tmp_path)
        ld = policy_mod.snapshot()
        payload = {"searched": ["https://platform.uplers.com/x", str(cfg)]}

        rendered = policy_mod.relativise_mapping(payload, ld)

        assert rendered != payload, "nothing was substituted at all"
        assert rendered["searched"][0] == "https://platform.uplers.com/x"
        assert list(path_hits(rendered, str(tmp_path))) == [], rendered
        assert "jobhunt.json" in rendered["searched"][1], rendered
