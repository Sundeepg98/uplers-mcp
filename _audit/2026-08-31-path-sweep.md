# 2026-08-31 - identity paths (uplers slice)

The full write-up lives in the Naukri repository, because the pass covered three repos at once
and the finding is the same class in all three:

    naukri-mcp  _audit/2026-08-31-path-sweep.md

This file records what happened HERE, so the numbers are findable from this repo alone. It names
no real value: `<given>` is the operator's given name, `<account>` his Windows account name.

## What was found

27 hits across 9 tracked files carried an absolute path whose first segment is `<given>` - the
README's install and registration examples, six audit slices, and both a docstring and two
assertions in `tests/test_path_hygiene.py`, plus one docstring in `uplers_server/policy.py`.
Two more lines carried `<account>` in a Windows user path, and four carried it bare.

## Why nothing caught it

**There was no rule.** `tests/test_path_hygiene.py` is thorough, but its subject is a TOOL RESULT
at runtime: it walks payloads and has never read a tracked file. `tests/test_pii_hygiene.py` does
walk `git ls-files`, and hunted fifteen shapes - email, phone, LinkedIn handles, credentials,
account ids - **none of them a filesystem path**.

Between the two, the hole was exact: payloads checked for paths, committed files checked for
everything but paths. The class was UNGUARDED, not under-guarded.

## What changed

`5e1b5f4`. 27 given-name and 2 account substitutions, plus 2 where the account was assembled from
parts and no path-shape regex could reach it. Every separator run was captured and re-emitted
byte for byte, so only the segment changed and the escaping did not - which matters, because
several of these lines exist precisely to show two spellings of one path differing.

325 lines appended to `tests/test_pii_hygiene.py`: three rules (Windows user path, drive root,
POSIX home) with the separator run written `+` rather than one character, two measured
allowlists, and five tests - including the narrow rule DERIVED from the shipped one and shown
failing on the doubled spelling. Every separator is built from `chr(92)`.

Driven over this repo's own pre-fix content at HEAD, the new check reports **29 findings**.

Suite **1706 -> 1711**, the +5 being exactly the five new tests.

## Not covered

Read section 8 of the Naukri write-up before treating this repo as clean. The largest unfixed
class is here: `tests/fixtures/talent_profile.json` is a captured live profile holding the
operator's real full personal name, and roughly 28 assertions across the talent, session, auth
and policy suites echo it. A personal name has no shape, so no rule added above can find it.
