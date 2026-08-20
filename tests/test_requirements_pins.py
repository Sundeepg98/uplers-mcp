"""The dependency pins, asserted rather than trusted.

THE HAZARD THIS GUARDS
----------------------
On 2026-08-20 the sibling naukri server's CI went red for a breakage no local
run could show. naukri declared `mcp[cli]>=1.25.0` with no upper bound. `mcp
2.0.0` shipped, relocating `mcp/server/fastmcp` to `mcp/server/mcpserver`, and
naukri imports the old path unconditionally -- so a CLEAN resolve picked 2.0.0
and all 55 of its test modules died at collection: "5 deselected, 55 errors",
zero tests run. Every LOCAL naukri run stayed green, because that venv held mcp
1.26.0 installed before 2.0.0 existed.

That is the class: an unbounded `>=` on a dependency whose next major moves an
import path is a time bomb whose fuse is lit by someone ELSE'S release, and a
local venv -- a cache of a resolve that happened in the past -- cannot see it.

WHY THESE TESTS READ FILES AS TEXT
----------------------------------
Because the alternative is the check that already failed to fail. Asserting
against the INSTALLED version (`importlib.metadata.version("mcp") < 2`) would
have passed happily in exactly the venv that hid naukri's bug for a full day.
The declaration is the thing under test, not the cache of an old resolve.

These tests are pure: no network, no install, two small reads of repo files.
The install itself is checked by scripts/clean_install_check.py, which throws
the cached resolve away and starts over.
"""

import re
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
REQUIREMENTS = REPO / "requirements.txt"
SERVER = REPO / "server.py"


def _requirement_lines(path):
    """Yield the non-comment, non-blank requirement lines of a pip file."""
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].strip()
        if line and not line.startswith("-"):
            yield line


def _name_of(requirement):
    """The distribution name at the head of a requirement string.

    The `@` and whitespace in the split set are load-bearing: PEP 508 direct
    references look like `jobcore @ git+https://.../jobcore@d1d44bb` and carry no
    version operator, so splitting on operators alone would return the whole URL
    as the "name". Exact-name matching also keeps `mcp-types` from being read as
    a line about `mcp`.
    """
    return re.split(r"[<>=\[!~;@\s]", requirement, maxsplit=1)[0].strip().lower()


def _mcp_lines():
    return [ln for ln in _requirement_lines(REQUIREMENTS) if _name_of(ln) == "mcp"]


def test_mcp_has_an_upper_bound():
    """See this module's docstring: unbounded is how naukri's build got broken."""
    lines = _mcp_lines()
    assert lines, "the mcp requirement disappeared from requirements.txt"
    assert any(re.search(r"<\s*\d", ln) for ln in lines), (
        "mcp must carry an upper bound. Its next major is code nobody has run "
        "this server against, and mcp has already moved an import path once. "
        "Found: %r" % lines
    )


def test_the_mcp_cap_is_not_narrowed_to_the_major_this_server_already_survives():
    """<2 would be naukri's fix cargo-culted onto a repo that does not need it.

    Measured 2026-08-20 in a throwaway venv with nothing borrowed from a local
    install: the resolve picked mcp 2.0.0, server.py imported, and the suite
    reported "443 passed, 1 skipped in 28.58s". Capping <2 here would pin a
    working server to an older major for no reason anyone could point at.
    """
    for line in _mcp_lines():
        assert not re.search(r"<\s*2(\.|\b)", line), (
            "this server runs on mcp 2.x via the dual-path import in server.py; "
            "capping it below 2 downgrades a server that is not broken: %r" % line
        )


def test_the_dual_path_import_that_earns_the_wider_cap_still_exists():
    """The cap and the import are ONE decision, so they are asserted together.

    `mcp[cli]<3` rather than `<2` is justified by exactly one thing: server.py
    imports MCPServer with a fallback to the 1.x FastMCP path, so both majors
    work. Delete that fallback and the justification evaporates -- this test
    fails first, at the place where the cap would have to narrow, instead of
    later on someone's clean checkout.
    """
    source = SERVER.read_text(encoding="utf-8")
    assert "from mcp.server import MCPServer" in source, (
        "the mcp 2.x import path is gone from server.py; if this server no "
        "longer supports mcp 2.x, requirements.txt must be capped <2"
    )
    assert "from mcp.server.fastmcp import FastMCP" in source, (
        "the mcp 1.x fallback import is gone from server.py; if 1.x is no "
        "longer supported, the requirements floor must be raised to >=2"
    )


def test_jobcore_is_not_a_requirement_line():
    """A `jobcore @ git+...` line here would silently clobber the editable install.

    Measured 2026-08-20 in this repo's own throwaway venv: after
    `pip install -e ../jobcore`, installing jobcore from the git URL printed
    "Attempting uninstall: jobcore / Successfully uninstalled" and the
    "Editable project location" line vanished from `pip show`. So every routine
    `pip install -r requirements.txt` would quietly disconnect a developer from
    the sibling checkout they were editing -- and pip prints no "already
    satisfied" line for a direct-URL requirement, so the clobber is invisible
    unless you go looking.

    jobcore stays a documented sibling step (see requirements.txt and the README).
    """
    for line in _requirement_lines(REQUIREMENTS):
        assert _name_of(line) != "jobcore", (
            "jobcore must stay out of requirements.txt -- it clobbers "
            "`pip install -e ../jobcore`: %r" % line
        )


def test_every_requirement_declares_a_floor():
    """A bare package name pins nothing and resolves to whatever shipped today.

    Deliberately a FLOOR check, not a ceiling check: capping every dependency
    would be cargo-culting. Only the package that has already moved an import
    path carries a ceiling here.
    """
    for line in _requirement_lines(REQUIREMENTS):
        assert re.search(r"[<>=~!]", line), (
            "%r declares no version at all" % line
        )
