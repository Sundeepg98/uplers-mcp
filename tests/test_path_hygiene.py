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
from uplers_server import config as uplers_config_mod
from uplers_server import policy as policy_mod
from uplers_server import profile_write

# The shape the brief names: a drive letter followed by a separator.
ABSOLUTE_LOCAL = re.compile(r"[A-Za-z]:[\\/]")

# Exact anchors for this box, so the sweep still bites on a POSIX runner where
# no drive letter exists. Substring checks against real roots cannot misfire on
# prose the way a general "looks absolute" heuristic would.
REPO_ROOT_TEXT = str(Path(__file__).resolve().parent.parent)
HOME_TEXT = str(Path.home())


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


def payload_of(result) -> dict:
    """The tool result as the dict a client actually receives."""
    if hasattr(result, "model_dump_json"):
        return json.loads(result.model_dump_json())
    return json.loads(json.dumps(result, default=str))


class TestNoToolResultCarriesALocalPath:

    async def test_no_offline_tool_payload_carries_an_absolute_local_path(
            self, monkeypatch, tmp_path, make_profile):
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
        }

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
        found = [
            (trail, text)
            for trail, text in leaks_in(payload_of(report))
        ]
        assert found == [], found


class TestTheRenderedPathIsStillAnAnswer:

    def test_two_different_searched_paths_do_not_render_alike(self):
        """The assertion that rules out a basename fallback.

        Three pairs, one per form the renderer can fall into, because the
        collapse is only visible when two paths share a filename and differ
        only above it. Under the anchor, under home, and under neither - that
        last one is the form a Linux CI runner hits with /tmp and the form the
        old basename fallback silently destroyed.
        """
        root = Path(uplers_config_mod.REPO_ROOT)
        pairs = (
            (root / "one" / "jobhunt.json", root / "two" / "jobhunt.json"),
            (Path.home() / "one" / "jobhunt.json",
             Path.home() / "two" / "jobhunt.json"),
            (Path("Z:/opt/one/jobhunt.json"), Path("Z:/opt/two/jobhunt.json")),
        )
        for left, right in pairs:
            rendered_left = policy_mod.display_path(str(left))
            rendered_right = policy_mod.display_path(str(right))
            assert rendered_left != rendered_right, (left, right, rendered_left)
            assert rendered_left != "jobhunt.json", rendered_left
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
        assert not ABSOLUTE_LOCAL.search(report.source), report.source
        assert HOME_TEXT not in report.source, report.source
        assert not ABSOLUTE_LOCAL.search(report.status), report.status

    async def test_the_profile_path_still_names_profile_json(self, make_profile):
        """Same pairing on the other reproduced field."""
        make_profile()

        result = await server.uplers_get_profile()

        assert result.path is not None
        assert result.path.endswith("profile.json"), result.path
        assert not ABSOLUTE_LOCAL.search(result.path), result.path
