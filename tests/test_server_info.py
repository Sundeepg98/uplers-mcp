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
#
# THE LOOKBEHIND IS LOAD-BEARING. A drive letter is ONE character, and
# without it this matches the "s:/" inside "https://" and reports every
# correct URL in a payload as a leak - measured on this suite, where the
# walker flagged two real platform.uplers.com URLs before it was tightened.
# An instrument that manufactures failures is worse than no instrument,
# because the usual repair is to delete the field that tripped it. The
# control for this line is test_the_leak_regex_does_not_fire_on_an_https_url.
ABSOLUTE_LOCAL = re.compile(r"(?<![A-Za-z])[A-Za-z]:[\\/]")


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

        # PRIMARY: the exact directory this test created, absent from the
        # payload. Platform-independent - the drive-letter rule below cannot
        # fire at all on the ubuntu runner that gates a merge for this repo,
        # so on its own it would certify nothing there. See
        # test_path_hygiene.path_hits for the measurement.
        primary = [
            (trail, text)
            for trail, text in strings_in(payload)
            if str(tmp_path) in text
        ]
        assert primary == [], primary
        # SECOND OPINION: shape-based, Windows-only.
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
        # NOT `== "git"`. That was instahyre's assertion and it went red on a
        # runner that pip-installs jobcore from a git URL - site-packages is
        # not a work tree, so `package` is the correct answer there. What must
        # hold is that jobcore answers SEPARATELY from this checkout, whichever
        # way it is installed. See TestTheJobcoreStampSurvivesBothInstallations.
        assert build["jobcore"]["source"] in ("git", "package"), build["jobcore"]
        assert build["jobcore"].get("commit") or build["jobcore"].get("version"), (
            build["jobcore"]
        )
        if build["jobcore"]["source"] == "git":
            assert build["jobcore"]["commit"] != build["code"]["commit"]

    async def test_the_docstring_says_how_to_detect_a_stale_process(self):
        """The payload is useless to a reader who is not told what to compare."""
        doc = server.uplers_server_info.__doc__ or ""

        assert "git rev-parse HEAD" in doc
        assert "stale" in doc.lower()

    async def test_it_names_the_tool_that_cannot_be_undone(self):
        payload = payload_of(await server.uplers_server_info())

        assert payload["irreversible_tools"] == ["uplers_apply"]


class TestTheJobcoreStampSurvivesBothInstallations:
    """The hole instahyre's CI found and neither this box nor this CI can see.

    jobcore is installed two different ways across this family. On the
    operator's box and on uplers' own runner it is an EDITABLE install from a
    real checkout, so `git rev-parse` answers and the stamp carries a commit.
    Elsewhere - a consumer that pip-installs it from a git URL, which is what
    the hosting plan targets - it lands in site-packages, which is not a work
    tree, so there is no commit to report and the stamp was correctly and
    uselessly `unknown`: silent in exactly the deployment where nobody can run
    `git log` to find out by hand.

    So the assertion cannot be "source == git". That is the assertion instahyre
    had, and it is what went red. What must hold is weaker and actually true:
    the stamp ANSWERS - with a commit, or with an installed version - in either
    installation.
    """

    def _reload_under(self, monkeypatch, git_present: bool):
        """Re-run buildinfo's module-level constants with git present or not.

        Removing git from PATH is a faithful stand-in for the site-packages
        case: jobcore's `resolve` funnels "no git executable" and "not a work
        tree" into the SAME `unknown()` branch, and that branch is exactly
        where the distribution fallback lives. Reloading rather than calling a
        helper means the test exercises the real module-level constant, which
        is the thing a payload actually carries.
        """
        import importlib

        from jobcore import buildinfo as jc
        from uplers_server import buildinfo as ub

        jc.invalidate_cache()
        if not git_present:
            monkeypatch.setattr(jc.shutil, "which", lambda name: None)
        return importlib.reload(ub)

    def test_the_jobcore_stamp_answers_in_either_installation(self, monkeypatch):
        """Both halves, so the tolerant assertion is not tolerance for a hole."""
        import importlib

        from jobcore import buildinfo as jc
        from uplers_server import buildinfo as ub

        try:
            # 1. as installed here: an editable install over a real checkout
            live = self._reload_under(monkeypatch, git_present=True)
            assert live.JOBCORE_BUILD.source in ("git", "package")
            assert live.JOBCORE_BUILD.commit or live.JOBCORE_BUILD.version

            # 2. as installed in site-packages: no work tree to interrogate
            packaged = self._reload_under(monkeypatch, git_present=False)
            assert packaged.JOBCORE_BUILD.source in ("git", "package"), (
                packaged.JOBCORE_BUILD
            )
            assert packaged.JOBCORE_BUILD.commit or packaged.JOBCORE_BUILD.version, (
                packaged.JOBCORE_BUILD
            )
        finally:
            monkeypatch.undo()
            jc.invalidate_cache()
            importlib.reload(ub)

    def test_the_version_does_not_appear_by_magic(self, monkeypatch):
        """CONTROL. Proves the fix is load-bearing and the tolerance is earned.

        Without a distribution name there is nothing to fall back TO, so the
        old derivation stays `unknown` off a work tree - which is precisely the
        defect. Asking the same question WITH the name is what produces the
        version. If this control ever passes on the first branch, the tolerant
        assertion above has stopped meaning anything.
        """
        import jobcore
        from jobcore import buildinfo as jc

        jc.invalidate_cache()
        monkeypatch.setattr(jc.shutil, "which", lambda name: None)
        try:
            old_way = jc.resolve(jobcore.__file__)
            assert old_way.source == "unknown", old_way
            assert old_way.version is None, old_way

            new_way = jc.resolve(jobcore.__file__, distribution="jobcore")
            assert new_way.source == "package", new_way
            assert new_way.version, new_way
        finally:
            jc.invalidate_cache()


class TestTheDeclaredSurfaceMatchesReality:
    """The payload's self-description is DECLARED, so this is where it is checked.

    `uplers_server_info` reads module constants and reaches for nothing - no
    `list_tools()`, no file, no git, no network - because it is the tool you
    call when the server's behaviour is already under suspicion. The price of
    that is a hand-maintained declaration, and a hand-maintained declaration
    goes stale silently. So the derivation that the TOOL must not do, this
    class does: every declared name is checked against the live registry, and
    every declared count against the sets pinned in tests/test_tools.py.

    THE ONE THAT MATTERS is
    test_every_declared_write_name_is_a_registered_tool together with
    test_the_declared_counts_match_the_pinned_sets. A new write landing without
    a line in the declaration is exactly the staleness this tool exists to
    catch, and a guard for it that could not go red would be worse than none -
    it would manufacture confidence at the one point the operator is relying on
    the server to tell the truth about its own blast radius. Both were planted
    -controlled on 2026-08-24: adding a fake name to PROFILE_WRITE_TOOL_NAMES
    reddens the first, and removing a real one from the declaration reddens the
    second.
    """

    @staticmethod
    async def _registered() -> set:
        return {tool.name for tool in await server.mcp.list_tools()}

    async def test_every_declared_write_name_is_a_registered_tool(self):
        """A declaration naming a tool that does not exist is a lie in the
        other direction, and it fails the same way: the reader trusts a census
        that no longer describes the server."""
        registered = await self._registered()

        declared = (
            list(server.REQUISITION_WRITE_TOOLS)
            + list(server.PROFILE_WRITE_TOOLS)
            + list(server.SHARED_CONFIG_WRITE_TOOLS)
            + list(server.LOCAL_STATE_ONLY_TOOLS)
            + list(server.IRREVERSIBLE_TOOLS)
            + list(server.ONE_WAY_DOOR_TOOLS)
        )

        missing = sorted(name for name in declared if name not in registered)
        assert missing == [], (
            "declared in uplers_server_info but NOT a registered tool: %s" % missing
        )

    async def test_the_declared_counts_match_the_pinned_sets(self):
        """The pinned sets in test_tools.py are the other end of the same rope.

        They are what an operator edits by hand when a write lands - the count
        assertions there exist to force that edit. This test makes the SAME
        edit fall due here, so a write cannot land in the server, be admitted
        to the pinned set, and still be invisible to the tool whose job is to
        report it.
        """
        from test_tools import (
            CONFIG_TOOL_NAMES,
            LOCAL_WRITE_TOOL_NAMES,
            PROFILE_WRITE_TOOL_NAMES,
            WRITE_TOOL_NAMES,
        )

        assert set(server.REQUISITION_WRITE_TOOLS) == WRITE_TOOL_NAMES
        assert set(server.PROFILE_WRITE_TOOLS) == PROFILE_WRITE_TOOL_NAMES
        assert set(server.SHARED_CONFIG_WRITE_TOOLS) == CONFIG_TOOL_NAMES
        assert set(server.LOCAL_STATE_ONLY_TOOLS) == LOCAL_WRITE_TOOL_NAMES

        # and the counts the PAYLOAD prints, not just the constants behind it
        payload = payload_of(await server.uplers_server_info())
        writes = payload["writes"]

        assert writes["reach_uplers"]["requisition"]["count"] == len(WRITE_TOOL_NAMES)
        assert writes["reach_uplers"]["profile"]["count"] == len(
            PROFILE_WRITE_TOOL_NAMES
        )
        assert writes["reach_the_shared_config"]["count"] == len(CONFIG_TOOL_NAMES)
        assert set(writes["local_state_only"]["tools"]) == LOCAL_WRITE_TOOL_NAMES

    async def test_the_resume_write_is_declared_a_one_way_door(self):
        """uplers_replace_resume must appear, and NOT in the apply list.

        Uplers keeps no previous copy of a resume, so the write is a one-way
        door on THEIR side; this server makes it recoverable only by taking a
        pre-flight snapshot to local disk. That is a different safety class
        from uplers_apply, which nothing anywhere can undo. Reporting them as
        one list would have to lie in one direction or the other, so this
        asserts BOTH the presence and the separation.
        """
        payload = payload_of(await server.uplers_server_info())
        block = payload["irreversible"]

        one_way = block["one_way_door_on_uplers_recoverable_only_locally"]
        assert "uplers_replace_resume" in one_way["tools"], block

        # and it is NOT flattened into the no-undo-anywhere list, whose
        # contract with every existing caller is `irreversible_tools`
        no_undo = block["no_undo_anywhere_in_uplers"]
        assert no_undo["tools"] == ["uplers_apply"], no_undo
        assert "uplers_replace_resume" not in no_undo["tools"], no_undo
        assert payload["irreversible_tools"] == ["uplers_apply"]

        # the local snapshot is the whole difference, so it has to be stated
        assert one_way["recoverable_by"] != no_undo["recoverable_by"]
        assert "snapshot" in one_way["recoverable_by"].lower()

    async def test_the_tool_counts_match_the_registry_and_the_banner(self):
        """53, and the public/authenticated split, both derived rather than believed.

        The split has exactly one definition: the `# THE AUTHENTICATED TIER`
        banner in server.py. Which side of that physical line a tool is defined
        on IS whether it needs an account, so the banner is parsed here rather
        than the tiers prose being trusted.
        """
        import re
        from pathlib import Path

        registered = await self._registered()
        counts = server.TOOL_COUNTS

        assert counts["total"] == len(registered)

        source = Path(server.__file__).read_text(encoding="utf-8").splitlines()
        banners = [
            index
            for index, line in enumerate(source)
            if line.startswith("# THE AUTHENTICATED TIER")
        ]
        assert len(banners) == 1, "the banner defines the split; there must be one"
        banner = banners[0]

        defined = re.compile(r"^async def (uplers_\w+)")
        above, below = set(), set()
        for index, line in enumerate(source):
            match = defined.match(line)
            if match:
                (above if index < banner else below).add(match.group(1))

        # every `async def uplers_*` in this module is a registered tool, so a
        # helper sneaking into the count would fail here rather than skew it
        assert above | below == registered, sorted(
            (above | below) ^ registered
        )
        assert counts["public"] == len(above), sorted(above)
        assert counts["authenticated"] == len(below), sorted(below)

        # and the payload prints the same numbers it was built from
        payload = payload_of(await server.uplers_server_info())
        headline = payload["capabilities"][0]
        assert "%d tools" % counts["total"] in headline, headline

    async def test_the_declaration_is_not_derived_from_the_registry(self, monkeypatch):
        """CONTROL for the property the whole design rests on.

        The instrument is a `list_tools` that RAISES. A tool reading module
        constants cannot notice; one that built its census by asking the
        registry - which is the obvious implementation, and the one that would
        make every assertion above tautological - dies on it. Without this,
        "reads module constants and nothing else" is a docstring claim with no
        measurement behind it.
        """

        async def explode():
            raise RuntimeError("uplers_server_info must not call list_tools()")

        monkeypatch.setattr(server.mcp, "list_tools", explode)

        payload = payload_of(await server.uplers_server_info())

        assert payload["writes"]["reach_uplers"]["requisition"]["count"] == 2
        assert payload["capabilities"]
        assert payload["out_of_scope_by_design"]
        assert payload["known_limits"]

    async def test_the_known_limits_carry_the_measured_404_routes(self):
        """Recorded so nobody re-runs the probes that established them.

        Both routes answered 404 on a live session with a good id, so the open
        question is the parameter space and NOT the session - which is the one
        thing a future session would otherwise get wrong, by assuming a fresh
        login is the retry that changes the answer.
        """
        from uplers_server import endpoints

        payload = payload_of(await server.uplers_server_info())
        limits = payload["known_limits"]["measured_404"]

        assert limits["routes"] == list(endpoints.MEASURED_404)
        assert "talent/outreach/outreached-people" in limits["routes"]
        assert "talent/outreach/get-employee-requests" in limits["routes"]
        assert "PARAMETER SPACE" in limits["the_open_question"]

        unresolved = payload["known_limits"]["unresolved_identifier_space"]
        assert "UNTESTED" in unresolved["entitlement_is_untested_not_answered"]
