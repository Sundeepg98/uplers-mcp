"""Run every leak test against every credential-echo transform, print the grid.

One cell per (test, transform). A cell is only acceptable RED: the build under
test is deliberately leaking the operator's bearer token, so a GREEN cell is a
leak this suite would have shipped.

    venv/Scripts/python scripts/leak_matrix.py

Prints a table and exits non-zero if any cell is green. Each transform is a
full pytest session over the guarded tests, so it takes a couple of minutes.

Adapted from `linkedin/scripts/leak_matrix.py`. Kept deliberately close to it
so a result here is comparable with that server's published grid rather than
being a differently-shaped number.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))

from credential_echo_control import TRANSFORMS  # noqa: E402

#: Every assertion in this repo whose job is to keep the credential inside the
#: process. Both halves are here on purpose: the Sanctum-shaped canaries, which
#: any detector catches, and the JWT-shaped ones, which are the real credential.
GUARDED = (
    "tests/test_session_lifecycle.py::TestTheTokenNeverAppearsAnywhere"
    "::test_no_payload_this_tool_can_produce_carries_the_token",
    "tests/test_session_lifecycle.py::TestTheTokenNeverAppearsAnywhere"
    "::test_no_token_reaches_a_log_line",
    "tests/test_session.py::test_describe_never_leaks_the_token",
    "tests/test_session.py::test_describe_never_leaks_a_jwt",
    "tests/test_session.py::test_check_auth_never_returns_the_token",
    "tests/test_session.py::test_check_auth_never_returns_a_jwt",
    "tests/test_talent_tools.py::test_auth_status_reports_false_on_401_and_never_prints_the_token",
    "tests/test_talent_tools.py::test_auth_status_never_prints_a_jwt",
)

PY = str(REPO / "venv" / "Scripts" / "python.exe")
if not Path(PY).is_file():                              # posix / CI
    PY = sys.executable


def run(transform: str) -> dict:
    env = dict(os.environ)
    env["UPLERS_LEAK_TRANSFORM"] = transform
    env["PYTHONPATH"] = str(REPO / "scripts")
    proc = subprocess.run(
        [PY, "-m", "pytest", "-p", "credential_echo_control", "-q", "--no-header",
         "-rA", "--tb=no", *GUARDED],
        cwd=str(REPO), env=env, capture_output=True, text=True,
    )
    verdicts = {}
    for line in proc.stdout.splitlines():
        for name in GUARDED:
            short = name.split("::")[-1]
            if line.startswith("PASSED ") and line.rstrip().endswith(short):
                verdicts[short] = "GREEN"
            elif line.startswith("FAILED ") and short in line:
                verdicts[short] = "red"
    return verdicts


def main() -> int:
    shorts = [n.split("::")[-1] for n in GUARDED]
    width = max(len(t) for t in TRANSFORMS) + 2
    print("\ncell = verdict of that leak test under that leaking build")
    print("red = the leak was caught.  GREEN = the leak shipped.\n")
    header = "transform".ljust(width) + "".join("%4d" % (i + 1) for i in range(len(shorts)))
    print(header)
    print("-" * len(header))

    green_cells = 0
    for transform in TRANSFORMS:
        verdicts = run(transform)
        row = transform.ljust(width)
        for short in shorts:
            verdict = verdicts.get(short, "??")
            green_cells += verdict != "red"
            row += "%4s" % ("." if verdict == "red" else "G" if verdict == "GREEN" else "?")
        print(row)

    print("\n  . = red (leak caught)   G = GREEN (leak shipped)   ? = not run\n")
    for index, short in enumerate(shorts, 1):
        print("  %d. %s" % (index, short))
    print("\ngreen cells: %d of %d" % (green_cells, len(TRANSFORMS) * len(shorts)))
    return 1 if green_cells else 0


if __name__ == "__main__":
    raise SystemExit(main())
