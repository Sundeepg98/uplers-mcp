# uplers auth-lifecycle slice - 2026-08-23

Slice: ADD `uplers_session_info`, RESHAPE `uplers_logout` to section 2 of
`_audit/2026-08-23-auth-contract.md`. NO `uplers_reauth` (ruled out by the
contract's table with evidence).

Commit: **`e9165d44bc311d27f22ad37b368f11968e3cd416`** on `master`. NOT pushed -
the wave lead pushes after review. Working tree clean.

## Tools and where they live

| Thing | File:line |
|---|---|
| `uplers_session_info(verify_live: bool = True) -> dict` | `uplers/server.py:2350` |
| `uplers_logout() -> dict` | `uplers/server.py:2411` |
| `credential_report(store)` | `uplers/uplers_server/session.py:383` |
| `_durability` / `_renewal` / `_what_it_means` | `uplers/uplers_server/session.py:421` / `:441` / `:445` |
| `session_info_offline(store, *, why_no_live_check, attempted=False)` | `uplers/uplers_server/session.py:470` |
| `session_info(store, client)` (async, live path) | `uplers/uplers_server/session.py:509` |
| `logout_report(store)` | `uplers/uplers_server/session.py:549` |
| Prose constants (`EXPIRY_IS_A_CEILING`, `RENEWAL_WHY`, ...) | `uplers/uplers_server/session.py:287-374` |
| New tests (32) | `uplers/tests/test_session_lifecycle.py` |
| The control | `uplers/scripts/presence_is_auth_control.py` |

The logic sits in `session.py` rather than inline in `server.py` because most of
what these tools return is prose, and prose that says how long a credential
lasts is load-bearing - a second copy in a docstring is a second copy to get
wrong.

## Test counts

| | count |
|---|---|
| Baseline, measured before any edit | **944 passed** |
| After the slice | **976 passed** (944 + 32) |

Both runs: `venv/Scripts/python.exe -m pytest tests -q`, full suite, green.

## The control, and its measured red

`uplers/scripts/presence_is_auth_control.py` - a pytest plugin in the house form
of `instahyre/scripts/permissive_scorer_control.py`. It replaces
`uplers_server.session.check_auth` with a build that answers `authenticated`
straight from `client.has_token()` and makes no request. That is the bug
Instahyre actually shipped, and the one Uplers invites through its anonymous
`guest_token`.

Against the new file:

    PYTHONPATH=scripts venv/Scripts/python -m pytest tests/test_session_lifecycle.py -q -p presence_is_auth_control

    4 failed, 28 passed in 2.40s

    FAILED tests/test_session_lifecycle.py::TestTheVerdictComesFromTheProbe::test_a_guest_200_is_null_not_false_and_not_true
    FAILED tests/test_session_lifecycle.py::TestTheVerdictComesFromTheProbe::test_a_transport_failure_is_null_with_the_reason_attached
    FAILED tests/test_session_lifecycle.py::TestTheVerdictComesFromTheProbe::test_a_401_with_a_token_present_is_a_real_false
    FAILED tests/test_session_lifecycle.py::TestTheVerdictComesFromTheProbe::test_a_real_yes_is_a_yes_and_says_where_it_came_from

Against the whole suite:

    PYTHONPATH=scripts venv/Scripts/python -m pytest tests -q -p presence_is_auth_control

    22 failed, 954 passed in 41.40s

    8  tests/test_auth.py            login handshake + refresh; completion condition IS check_auth
    7  tests/test_session.py         check_auth's own unit tests
    4  tests/test_session_lifecycle.py   the four above
    3  tests/test_talent_tools.py    uplers_auth_status's honesty tests

The fourth red was NOT predicted and is the best of them. `test_a_real_yes...`
asserts `signed_in_as == "Sundeep G"` on a genuine yes; the presence build dies
with `KeyError` because it has no response body to read a name out of. That is
the property from the other side: a true verdict here carries the evidence that
produced it, so a build that cannot produce evidence cannot fake the verdict
past that line either. Recorded in the control's docstring.

Deliberately GREEN under the control, and the asymmetry is the point:
every `verify_live=False` test (that path never calls `check_auth`), every
expiry test (`credential_report` reads the token, not the verdict), the leak
sweep (a permissive verdict prints no token), and
`test_no_token_and_a_401_is_false_not_null` - which is the file's own control
against a suite that merely asserts "everything is null" and would pass under
any build at all.

## What the contract asked for, and what shipped

Verified by rendering a real payload (temp store, fabricated JWT, no network):

* `server`, `authenticated`, `checked_against`, `live_check`, `credential`,
  `supporting`, `credential_source`, `durability`, `renewal`, `on_expiry` -
  all present, exact names.
* `credential`: `kind`=`bearer_token`, `name`=`token`, `format` from
  `token_format()`, `expires_at`/`expires_in_days`/`expired` from the JWT `exp`,
  `expiry_source`, `expiry_is_authoritative`.
* **`expiry_is_authoritative` is `false`, unconditionally, on every token
  shape** - it is a module constant (`EXPIRY_IS_AUTHORITATIVE`), not something
  computed per call, so no branch can quietly promote it. Its prose says the
  date is a CEILING the token claims, cites the SHORT-LIVED / roughly-daily
  facts from this server's own docstrings, and says only the live check settles
  it. Asserted clause by clause, not just the boolean.
* `expired` is **null** (never false) for `sanctum`, `opaque`, a JWT with no
  `exp`, and no token at all. Still capable of `true` - pinned by
  `test_a_past_exp_is_expired_true`, otherwise null is not a finding.
* `supporting: []` with the reason in `credential_source` prose.
* `durability.stored_in` goes through `policy.display_path` (renders as
  `~/AppData/.../session.json` - no drive letter, still names a file).
* `renewal`: `silent_renew_available: false`, `tool: null`, `why` carrying the
  backwards-layers argument, the session-only cookies, the 214-route sweep, and
  `uplers_login()` as the recovery.
* `verify_live=False` constructs no client at all - asserted against the
  CONSTRUCTOR (`NoNetwork` raises), because a shape assertion would pass even if
  a request had been spent first.
* `authenticated` comes from `check_auth` and nowhere else; nothing re-derives,
  softens, or backfills it.

## Four judgement calls the lead should see

**1. `uplers_logout` returns a plain dict, not `AuthStatus`.** Two reasons and
the second is the real one: `AuthStatus` has no field for `scope` /
`what_is_lost` / `recover_by`, AND it inherits `Compact`, whose
`@model_serializer` PRUNES any field equal to `None` / `[]` / `{}` / `""`. Under
a pydantic model the contract's `authenticated: null` and `expires_at: null`
would be silently DELETED from the payload - the exact nulls this contract
exists to preserve. `uplers_session_info` returns a dict for the same reason.
`uplers_filter_options` already returns `-> dict`, so this is not a new pattern
in the repo. `tests/test_talent_tools.py:1105` updated for the new shape,
keeping both sentences it already owned.

**2. A NAMED departure from the contract's fixed `"authenticated": false` in
`logout`.** `SessionStore.clear()` catches `OSError` and returns `False`, which
means "nothing was there" and "the unlink failed" are indistinguishable. On
Windows a lock can survive an unlink that did not raise. Claiming
`authenticated: false` on a token still sitting on disk is exactly the class of
lie this contract exists to kill, so the removal is CONFIRMED
(`store.path.is_file()`) and a failed one returns `authenticated: null`,
`cleared: false`, under a **named `removal_failed: true` flag** with a reason
saying the credential may still work. Per the contract preamble - a genuine
difference says so in a NAMED FIELD rather than giving an existing one a quietly
different meaning. Covered by
`test_it_never_raises_even_when_the_unlink_fails`. **Flag it if the lead wants
the contract's flat `false` instead.**

**3. Two ISO spellings now coexist in this server, and I did not unify them.**
The contract specifies `"YYYY-MM-DDTHH:MM:SSZ"`; `session.py`'s existing `_iso()`
renders `+00:00` and `uplers_auth_status` already publishes that. I added
`_iso_z()` for `session_info` only, so the new tool matches the contract and no
existing tool's output moves. Same instant, two spellings, in one server.
Unifying them means changing `SessionStore.describe()` and moving
`uplers_auth_status`'s output - out of scope for this slice, and a decision for
the lead. Documented in `_iso_z`'s docstring.

**4. README heading was already stale, and I corrected it.** The auth-tier
heading read "The 17 tools" over a table of **18** rows -
`uplers_my_assessments` landed in `aa150d6` without the count being bumped. I
added my row and set it to 19, with a one-line note in the README saying why the
number jumped by two. Correcting an existing drift, not introducing one.

## Also updated

* `tests/test_tools.py` - tool count **42 -> 43**, `uplers_session_info` added to
  `AUTH_TOOL_NAMES`, plus a new assertion that `uplers_reauth` is NOT in the
  surface (the tripwire for somebody shipping the decoy later). Nothing weakened;
  the `WRITE_TOOL_NAMES == 2`, `CONFIG_TOOL_NAMES == 1` and
  `PROFILE_WRITE_TOOL_NAMES == 2` invariants are untouched.
* `tests/test_path_hygiene.py` - `uplers_session_info(verify_live=False)` and
  `uplers_logout()` added to the offline leak sweep. `durability.stored_in` and
  `scope` each render a path on purpose, which makes them the two likeliest leak
  sites in the server.

## Constraints - all held

* `uplers_apply` NEVER called, at any point.
* The real `data/session.json` NEVER read, written or deleted. Verified after
  the fact: mtime still `Aug 21 11:06`, two days before this slice. Every test
  points both `server._session_store` and `session.session_path` at `tmp_path`,
  autouse.
* No browser launched. `auth.login_via_browser` raises in the new file, autouse.
* No `uplers_logout` run against the real store - the one call in
  `test_path_hygiene.py` deletes a file that test wrote in `tmp_path`.
* Strict ASCII verified programmatically across all 8 touched files: zero
  codepoints > 126.
* Commit on `master`, repo's existing message style, no `Co-Authored-By`, no
  `Claude-Session`. NOT pushed.
* Only `mcp-servers/uplers` touched. The two reference files
  (`_audit/2026-08-23-auth-contract.md`, `linkedin/linkedin_server/auth.py`) and
  `instahyre/scripts/permissive_scorer_control.py` were read only.

## Could not do

Nothing in the brief was blocked. The three open items above (2, 3, 4) are
decisions surfaced for the lead, not failures - each is implemented in the way I
judged most honest, and each is cheap to reverse.

---

# Addendum - `renewal.session_lapses_at` (2026-08-23, wave-lead follow-up)

Wave lead ruled on all four flagged items (dicts KEEP, `removal_failed` KEEP and
now the family rule, two ISO spellings LEAVE as a known wart, README fix
accepted) and added one uniform field group to `renewal` across all four
servers.

## What was added

    "session_lapses_at": str|null,        # ISO8601, ...Z spelling
    "session_lapses_in_days": float|null, # round(seconds/86400, 1)
    "session_lapses_source": str          # which credential governs, BY NAME

Definition: the date past which NO SILENT RENEW CAN HELP and the operator must
sign in by hand. It is a different question from `credential.expires_at` ("when
does this CREDENTIAL die"), and on naukri the two answers differ by 188 days -
its `nauk_at` measures +0.02 days while the server re-mints it silently, so a
client comparing `expires_at` across four servers would read naukri as half an
hour from death.

## What it does on uplers

There is no silent renew here, so the session lapses exactly when the bearer
token does: `session_lapses_at` / `session_lapses_in_days` take the SAME values
as `credential.expires_at` / `expires_in_days`, and go null together whenever
those are null.

The equality is **by construction, not by coincidence**: `_renewal` now takes
the already-built `credential` dict rather than rebuilding it, so a rounding
tick cannot put a tenth of a day between two fields defined to be equal. Both
call sites (`session_info` and `session_info_offline`) build the credential once
and hand the same object to both blocks.

`session_lapses_source` carries two things:
1. that the two dates coincide **because no renewal path exists** - with nothing
   to renew from, the session cannot outlive the credential that carries it;
2. **the ceiling warning, repeated here** rather than left to
   `expiry_is_authoritative`. This is the field most likely to be read as a
   deadline, so it says outright that the date is the token's own `exp` claim,
   that it is the LATEST the session could possibly still be good and not how
   long it will last, that Uplers revokes server-side far sooner, and that
   planning against it as a runway is wrong in the expensive direction.

Null handling unchanged: both dates null together, with the missing fact NAMED -
`no token is stored` / `a sanctum token keeps its expiry on Uplers' servers` /
`the stored JWT carries no readable exp claim`. Never a `0.0`, which would read
as "today", and never a `false`.

## Locations

| Thing | File:line |
|---|---|
| `SESSION_LAPSES_SOURCE` / `SESSION_LAPSES_UNKNOWN` | `uplers/uplers_server/session.py:352` / `:367` |
| `_lapse_unknown_reason(fmt)` | `uplers/uplers_server/session.py:477` |
| `_renewal(credential)` | `uplers/uplers_server/session.py:486` |
| 7 new tests | `uplers/tests/test_session_lifecycle.py` (4 named + one 4-case parametrize) |

## Counts

| | count |
|---|---|
| Before this addendum | 976 passed |
| After | **983 passed** (976 + 7) |

Control re-measured, and the number of reds does NOT move - which is the point:

    PYTHONPATH=scripts venv/Scripts/python -m pytest tests/test_session_lifecycle.py -q -p presence_is_auth_control
    4 failed, 35 passed in 2.48s        (was 4 failed, 28 passed)

    PYTHONPATH=scripts venv/Scripts/python -m pytest tests -q -p presence_is_auth_control
    22 failed, 961 passed in 32.08s     (was 22 failed, 954 passed)

The same four fail. The seven new tests stay GREEN under the control by design:
they pin what a no-renewal platform reports about when the operator must sign in
by hand, and `_renewal` is handed the credential block, never the verdict, so a
broken verdict cannot reach them. Recorded in the control's docstring as a
RE-MEASURED block, per the house form.

## Tests added

* `test_session_lapses_at_tracks_the_credential_exactly` - both dates equal to
  the credential's, `...Z` spelling.
* `test_the_lapse_source_names_the_no_renewal_reason_and_the_ceiling` - asserts
  the no-renewal clause AND the forwarded ceiling warning, clause by clause.
* `test_an_unknowable_lapse_is_null_and_never_zero` - parametrized over no
  token / sanctum / opaque / JWT-without-exp; null dates, named reason.
* `test_the_lapse_keys_are_present_on_the_live_path_too` - exact key set on
  `renewal`, pinning that both paths build it identically.

README's `uplers_session_info` row extended with the field.

Commit: PENDING (filled in below after the commit lands).

Constraints held again: `uplers_apply` never called; real `data/session.json`
untouched (mtime still `Aug 21 11:06`); no browser; strict ASCII; no AI trailer.
