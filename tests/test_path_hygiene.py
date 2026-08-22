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
import re
from pathlib import Path

import pytest

import server
from jobcore import config as jobcore_config
from uplers_server import config as uplers_config_mod
from uplers_server import policy as policy_mod
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
    """
    if isinstance(node, dict):
        for key, value in node.items():
            yield from path_hits(value, needle, "%s.%s" % (trail, key))
    elif isinstance(node, (list, tuple)):
        for index, value in enumerate(node):
            yield from path_hits(value, needle, "%s[%d]" % (trail, index))
    elif isinstance(node, str):
        if needle and needle in node:
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
