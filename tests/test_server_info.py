"""uplers_server_info() - the tool that says what code this process holds.

The defect this closes is not a missing field. On 2026-08-21 a fix that was
already committed to disk was diagnosed as a regression, because every check
available for "did the fix load" was a behavioural fingerprint - does this
field appear, is that count right - and a stale process passes and fails those
for the same reasons a buggy one does.

Two properties make the answer trustworthy, and both are asserted here:

  * THE STAMP IS FROZEN AT IMPORT. A per-call `git rev-parse` run from a stale
    process reports the NEW commit sitting on disk, which is worse than
    reporting nothing - it reads as confirmation that the fix is loaded, and
    what it confirms is false.
  * JOBCORE IS STAMPED SEPARATELY. This server's scoring IS jobcore's, so a
    stale jobcore is exactly as invisible as a stale server and one commit
    field covering only this checkout would hide half the surface.
"""

from __future__ import annotations

import json
import re

import pytest

import server
from uplers_server import policy as policy_mod

# A drive letter followed by a separator: "D:\", "C:/". The one shape that
# proves a raw local path survived into a payload.
ABSOLUTE_LOCAL = re.compile(r"[A-Za-z]:[\\/]")


def payload_of(result) -> dict:
    """The tool result as the dict a client actually receives."""
    return json.loads(result.model_dump_json())


def strings_in(node, trail="$"):
    """Every string in a payload, with the path that reached it."""
    if isinstance(node, dict):
        for key, value in node.items():
            yield from strings_in(value, "%s.%s" % (trail, key))
    elif isinstance(node, (list, tuple)):
        for index, value in enumerate(node):
            yield from strings_in(value, "%s[%d]" % (trail, index))
    elif isinstance(node, str):
        yield (trail, node)


class TestTheStampIsFrozen:

    async def test_the_stamp_is_not_re_resolved_per_call(self, monkeypatch):
        """Calling the tool must never shell out to git.

        The instrument is a subprocess.run that RAISES. A frozen constant read
        cannot notice; an implementation that resolves per call dies on it.
        RuntimeError deliberately: jobcore's _run_git catches OSError,
        SubprocessError and ValueError and turns them into an "unknown" stamp,
        so any of those three would be silently absorbed and the test would
        pass against the very implementation it exists to reject.
        """
        from jobcore import buildinfo as jc_buildinfo

        def explode(*args, **kwargs):
            raise RuntimeError("git was invoked on a request path")

        # Pinned so the probe is deterministic on a box with no git: without
        # it resolve() short-circuits on `which` and never reaches subprocess.
        monkeypatch.setattr(jc_buildinfo.shutil, "which", lambda name: "git")
        monkeypatch.setattr(jc_buildinfo.subprocess, "run", explode)

        first = payload_of(await server.uplers_server_info())
        second = payload_of(await server.uplers_server_info())

        assert first["build"]["code"] == second["build"]["code"]
        assert first["build"]["jobcore"] == second["build"]["jobcore"]

    async def test_the_payload_carries_a_commit_and_a_dirty_flag(self):
        """Both halves of "is this checkout what the commit says" must be there.

        A commit alone answers nothing when the tree has uncommitted edits, and
        `dirty` alone names no baseline to be dirty against.
        """
        payload = payload_of(await server.uplers_server_info())
        code = payload["build"]["code"]

        assert code["source"] == "git", code
        assert code["commit"], code
        assert re.fullmatch(r"[0-9a-f]{12}", code["commit"]), code["commit"]
        assert isinstance(code["dirty"], bool), code

    async def test_the_payload_leaks_no_absolute_path(self, monkeypatch,
                                                      tmp_path, make_profile):
        """Not one string in the payload may carry this machine's layout.

        A config file is written and bound on purpose: with the suite's
        `JOBHUNT_CONFIG=:none:` the source field is None and a raw-path
        implementation would go unmeasured.
        """
        make_profile()
        config_file = tmp_path / "jobhunt.json"
        config_file.write_text(json.dumps({"scoring": {}}), encoding="utf-8")
        monkeypatch.setenv("JOBHUNT_CONFIG", str(config_file))
        policy_mod.invalidate()

        payload = payload_of(await server.uplers_server_info())

        leaks = [
            (trail, text)
            for trail, text in strings_in(payload)
            if ABSOLUTE_LOCAL.search(text)
        ]
        assert leaks == [], leaks

    async def test_jobcore_is_stamped_separately_from_uplers(self):
        """Two repositories, two stamps, and they are not the same object.

        Scoring lives in jobcore, so a stale jobcore changes this server's
        numbers while this server's own commit reads current.
        """
        payload = payload_of(await server.uplers_server_info())
        build = payload["build"]

        assert "code" in build and "jobcore" in build
        assert build["jobcore"]["source"] == "git", build["jobcore"]
        assert build["jobcore"]["commit"] != build["code"]["commit"]

    async def test_the_docstring_says_how_to_detect_a_stale_process(self):
        """The payload is useless to a reader who is not told what to compare."""
        doc = server.uplers_server_info.__doc__ or ""

        assert "git rev-parse HEAD" in doc
        assert "stale" in doc.lower()

    async def test_it_names_the_tool_that_cannot_be_undone(self):
        payload = payload_of(await server.uplers_server_info())

        assert payload["irreversible_tools"] == ["uplers_apply"]
