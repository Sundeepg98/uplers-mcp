# Slice: make `uplers_server_info` honest, and fix four documentation defects

Date: 2026-08-24
Tree: `D:\workspace\projects\job-hunting\mcp-servers\uplers`, branch `master`, baseline commit `883c786`
Status: COMPLETE. Nothing committed - staged nothing, committed nothing.

---

## Baseline, verified before any edit

```
git status --porcelain   ->  only the five untracked _audit/_slices/*.md
./venv/Scripts/python.exe -m pytest tests/ -q   ->  1346 passed in 74.06s
```

Both matched the brief, so everything below is this slice's own work rather than
inherited breakage.

## Test count

| | |
|---|---|
| before | **1346 passed** |
| after | **1352 passed** (42.90s) |
| delta | +6, all in `tests/test_server_info.py::TestTheDeclaredSurfaceMatchesReality` |

No test was deleted, skipped or xfailed. `tests/test_tools.py` is byte-identical to
HEAD (`git diff --stat tests/test_tools.py` is empty) - the planted control there
was reverted with `git checkout`.

## Files touched

```
 README.md                  |  65 +++++---
 server.py                  | 363 ++++++++++++++++++++++++++++++++++++++++++++-
 tests/test_server_info.py  | 196 ++++++++++++++++++++++++
 uplers_server/endpoints.py | 132 +++++++++++++----
 uplers_server/models.py    |  32 ++++
 5 files changed, 733 insertions(+), 55 deletions(-)
```

Every `server.py` hunk is inside the `uplers_server_info` region:

```
@@ -2086,0 +2087,336 @@ async def uplers_config(...)      <- the constants block, immediately above tool 17
@@ -2116,0 +2453,20 @@ async def uplers_server_info()    <- docstring paragraph
@@ -2138   +2494,6 @@ async def uplers_server_info()    <- the return
```

---

## Job 1 - the payload

### Final `uplers_server_info` top-level keys

```
server, build, config, tiers, irreversible_tools,
capabilities, writes, irreversible, out_of_scope_by_design, known_limits
```

The first five are unchanged. `irreversible_tools` is still exactly
`["uplers_apply"]`, which the pre-existing
`test_it_names_the_tool_that_cannot_be_undone` still asserts.

### Shape of the five new blocks

- `capabilities` - 9 grouped lines, not 53. Opens with the counts
  (`53 tools. 24 need no account at all; 29 read or write his signed-in Uplers
  account.`), which are interpolated at import from `TOOL_COUNTS`, so the prose
  and the checked number cannot drift apart.
- `writes` - `counted_by` / `reach_uplers.{requisition,profile}` /
  `reach_the_shared_config` / `local_state_only` / `not_a_census_of_local_disk` /
  `gate`. Counts 2 / 4 / 1, each `len()` of its declaring tuple.
- `irreversible` - `no_undo_anywhere_in_uplers` (`uplers_apply`, `recoverable_by:
  "nothing"`), `one_way_door_on_uplers_recoverable_only_locally`
  (`uplers_replace_resume`, with `recoverable_by` naming the pre-flight snapshot
  and a `caveat` that the snapshot restores the FILE not the RECORD), and
  `why_two_lists_and_not_one`.
- `out_of_scope_by_design` - 6 `{what, why}` entries (see finding 9).
- `known_limits` - `measured_404` (the two routes, the date, and that the open
  question is the parameter space and not the session) and
  `unresolved_identifier_space` (the `hr_id` space, and that entitlement is
  UNTESTED rather than answered).

### The tool still reaches for nothing

The five blocks are module constants defined immediately above the tool
(`TOOL_COUNTS`, `REQUISITION_WRITE_TOOLS`, `PROFILE_WRITE_TOOLS`,
`SHARED_CONFIG_WRITE_TOOLS`, `LOCAL_STATE_ONLY_TOOLS`, `IRREVERSIBLE_TOOLS`,
`ONE_WAY_DOOR_TOOLS`, `CAPABILITIES`, `WRITE_CENSUS`, `IRREVERSIBLE`,
`OUT_OF_SCOPE_BY_DESIGN`, `KNOWN_LIMITS`). No `list_tools()`, no file read, no
git, no network, no database was added. The derivation the tool must not do is
done in the suite instead, and control 4 below proves that property can fail.

---

## Job 2 - the four documentation defects

1. **`QP_IS_SAVED_FILTER` moved out of "Recorded, deliberately NOT built".**
   Call sites verified first: `uplers_server/saved_filter.py` imports it and
   `uplers_platform_saved_jobs` sends it via `saved_filter.saved_jobs_params()`
   (`server.py:3365`). It now sits under a new `--- Read query parameters ---`
   banner with all contract detail kept (integer `1`, the EXCLUSIVE
   short-circuit, the in-house variant). Its closing line changed from "Pin both
   facts with a test before building on this" to what is actually true: both
   facts ARE pinned, by `assert_integer_one`, the `_ALLOWED` filter refusal, and
   `tests/test_saved_filter.py`.

2. **The Writes header corrected.** Was
   `--- Writes (shapes recorded; only job-not-interested is built) ---`. Verified
   by call-site census: `EP_INTRESTED` (server.py:3605, 3613), `EP_NOT_INTERESTED`
   (3671, 3680) and `EP_PROFILE_UPSERT` (3285, 3312, 3771, 3794, 3857, 3885) are
   BUILT; `EP_CANCEL_OPPORTUNITY` and `EP_UPDATE_SAVED_HR` have zero call sites
   anywhere outside `endpoints.py`. The header now names both groups. A separate
   note on `EP_PROFILE_UPSERT` records its TWO users and that they send different
   bodies down one route: `field="skills"` as JSON, `field="resume"` as multipart.

3. **`find-similar-job` reason 1 withdrawn as false, refusal kept.**
   `EP_TAILOR_JOBS = "talent/hr/tailor-jobs"  # POST JSON {HR_Number}` sits under
   `--- Reads ---` and `uplers_tailored_jobs` calls `post_json` on it
   (server.py:2667), so the "FIRST non-write POST" claim was untrue and predated
   by that route. The refusal now reads "TWO reasons", and the third is recorded
   as WITHDRAWN with why - deleted reasons get re-derived from the same mistaken
   premise. The correction states that the census counts by EFFECT, never by HTTP
   verb.

4. **README tool counts.** Split derived from the `# THE AUTHENTICATED TIER`
   banner at `server.py:2143`: **24 public + 29 authenticated = 53**, cross-checked
   against `list_tools()`. Fixed in every occurrence - see finding 4 for the ones
   beyond the three the brief named.

**Plus:** the two `MEASURED_404` routes added to `endpoints.py` under a new
`--- Measured unreachable ---` banner, deliberately a different class from
"recorded, deliberately NOT built" (those work and are not called; these were
called and did not answer), carrying the 2026-08-23 date and the note that the
open question is the parameter space rather than the session.

---

## Planted controls - every new guard shown failing

Five planted, five red, all reverted, suite green after each.

### Control 1 - THE ONE THE EXERCISE IS FOR
A new write lands in the pinned set and the declaration does not mention it.
Planted `"uplers_replace_cover_letter"` into `PROFILE_WRITE_TOOL_NAMES` in
`tests/test_tools.py`.

```
        assert set(server.REQUISITION_WRITE_TOOLS) == WRITE_TOOL_NAMES
>       assert set(server.PROFILE_WRITE_TOOLS) == PROFILE_WRITE_TOOL_NAMES
E       AssertionError: assert {'uplers_repl...date_profile'} == {'uplers_repl...date_profile'}
E
E         Extra items in the right set:
E         'uplers_replace_cover_letter'
E         Use -v to get more diff

tests\test_server_info.py:326: AssertionError
=========================== short test summary info ===========================
FAILED tests/test_server_info.py::TestTheDeclaredSurfaceMatchesReality::test_the_declared_counts_match_the_pinned_sets
1 failed, 5 passed in 2.43s
```

### Control 2 - the resume write drops out of the one-way-door declaration
`ONE_WAY_DOOR_TOOLS = ()`.

```
        one_way = block["one_way_door_on_uplers_recoverable_only_locally"]
>       assert "uplers_replace_resume" in one_way["tools"], block
E       AssertionError: {'no_undo_anywhere_in_uplers': {'tools': ['uplers_apply'], 'why': "Expressing interest on Uplers IS applying: their ow...s. `irreversible_tools` stays exactly the first list, which is what every existing caller of this tool already reads.'}
E       assert 'uplers_replace_resume' in []

tests\test_server_info.py:355: AssertionError
=========================== short test summary info ===========================
FAILED tests/test_server_info.py::TestTheDeclaredSurfaceMatchesReality::test_the_resume_write_is_declared_a_one_way_door
1 failed, 5 passed in 1.66s
```

### Control 3 - the declaration names a tool that does not exist
`REQUISITION_WRITE_TOOLS` grew `"uplers_withdraw"`.

```
        missing = sorted(name for name in declared if name not in registered)
>       assert missing == [], (
            "declared in uplers_server_info but NOT a registered tool: %s" % missing
        )
E       AssertionError: declared in uplers_server_info but NOT a registered tool: ['uplers_withdraw']
E       assert ['uplers_withdraw'] == []
E
E         Left contains one more item: 'uplers_withdraw'
E         Use -v to get more diff

tests\test_server_info.py:305: AssertionError
=========================== short test summary info ===========================
FAILED tests/test_server_info.py::TestTheDeclaredSurfaceMatchesReality::test_every_declared_write_name_is_a_registered_tool
1 failed in 1.50s
```

### Control 4 - the tool derives its census from the registry
Planted `await mcp.list_tools()` into `uplers_server_info`. This is the control
for "reads module constants and nothing else", and without it that sentence is a
docstring claim with no measurement behind it.

```
server.py:2478: in uplers_server_info
    await mcp.list_tools()   # PLANTED CONTROL - the forbidden derivation
    ^^^^^^^^^^^^^^^^^^^^^^
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _

    async def explode():
>       raise RuntimeError("uplers_server_info must not call list_tools()")
E       RuntimeError: uplers_server_info must not call list_tools()

tests\test_server_info.py:425: RuntimeError
=========================== short test summary info ===========================
FAILED tests/test_server_info.py::TestTheDeclaredSurfaceMatchesReality::test_the_declaration_is_not_derived_from_the_registry
1 failed in 1.62s
```

### Control 5 - the public/authenticated split goes stale
`TOOL_COUNTS` set to 25/28, total left at 53, so only the banner parse can catch it.

```
>       assert counts["public"] == len(above), sorted(above)
E       AssertionError: ['uplers_assess_fit', 'uplers_company_intel', 'uplers_config', 'uplers_daily_brief', 'uplers_delete_alert', 'uplers_get_market_stats', ...]
E       assert 25 == 24
E        +  where 24 = len({'uplers_assess_fit', 'uplers_company_intel', 'uplers_config', 'uplers_daily_brief', 'uplers_delete_alert', 'uplers_get_market_stats', ...})

tests\test_server_info.py:405: AssertionError
=========================== short test summary info ===========================
FAILED tests/test_server_info.py::TestTheDeclaredSurfaceMatchesReality::test_the_tool_counts_match_the_registry_and_the_banner
1 failed in 1.58s
```

---

## Findings that contradicted or exceeded the brief

**1. The agent-read set is 7 tools, not 4.** `AGENT_READ_TOOL_NAMES` holds
`uplers_agent_readthrough`, `uplers_platform_saved_jobs`, `uplers_my_preferences`,
`uplers_assessment_gates`, `uplers_email_scan`, `uplers_scanned_jobs`,
`uplers_agent_settings`. The brief's framing of "the READ half is built" is right;
the size is bigger than a reader of the brief would assume.

**2. `LOCAL_WRITE_TOOL_NAMES` does not mean what its name says, and the brief's
"local-state-only writes that never reach Uplers" is a different category.** The
set has 3 members but only `uplers_sync_profile_from_uplers` writes anything - the
two `list_*_snapshots` tools are pure disk READS, and the set's own comment in
`test_tools.py` says so. Meanwhile plenty of tools that DO write local state
(`uplers_sync_index`, save/unsave, track/update_status, the alert tools,
`uplers_set_profile`, `uplers_logout`) are not in it. I declared the pinned set
verbatim, said in `local_state_only.note` that the label overstates two of the
three, and added `not_a_census_of_local_disk` naming the others so the block
cannot be misread as a local-disk census. **Worth a ruling:** if you want a real
local-write census it is a different slice, and the set probably wants renaming.

**3. The `find-similar-job` refusal carried a SECOND stale fact the brief did not
flag.** Reason 1 also stated the census as "(2 requisition writes, 2 profile
writes, 1 config write)" - profile writes have been 4 since the resume pair
landed. Both errors left with the withdrawn reason.

**4. README had more stale counts than the three named.** Also fixed, each
measured rather than guessed: `Tools | **39**` -> 53 (24 public / 29 authenticated);
`Tests | **727**` -> 1,346; `Size | 8,120 / 8,577` -> 16,659 / 21,086 (measured
`wc -l server.py uplers_server/*.py` and `tests/*.py`); `12 talent/* routes` ->
26 `talent/*` plus `v2/assessments` (derived from the call-site census - 26 built
`talent/*` constants including `EP_DOWNLOAD_RESUME` in `resume_write.py`);
`## The public tier: 23 tools` and its "twenty-two"/"seventeen that do" paragraph;
`Six routes under it are now read` -> twelve; and the Playwright note's
"22 public / sixteen authenticated" -> 24 / twenty-eight.

**5. `### The 23 tools` heading sat over a table that was SIX ROWS SHORT** - no row
for `uplers_email_scan`, `uplers_scanned_jobs`, `uplers_agent_settings`,
`uplers_replace_resume`, `uplers_restore_resume`, `uplers_list_resume_snapshots`.
Correcting the heading to 29 without adding the rows would have introduced a fresh
lie, so I wrote the six rows from each tool's own docstring and measured contract
details. The table now holds 29 rows. **This is the largest judgement call in the
slice - it is content authoring, not a count fix.** The README's own parenthetical
note (which recorded the same drift happening once before) was rewritten to record
that it has now happened twice.

**6. `### The 18 tools` heading is CORRECT and I left it alone.** Its table is 11
rows but the rows collapse several tools each; counting NAMES gives exactly 18.
Flagging because it looks stale at a glance and the next reader may "fix" it.

**7. README contains pre-existing non-ASCII** - U+00B1 (line 275), U+00E9 (347,
348), U+20B9 (298, 307, 308), all in currency and measurement prose. Not
introduced by this slice and not touched; the edit script asserts the non-ASCII
character multiset is unchanged before writing. All four modified `.py` files are
strict ASCII. Flagging only because the house rule is strict ASCII.

**8. `uplers_server/models.py` had to be edited, and it was not in my owned
list.** `ServerInfo` lives there and new top-level keys require declared fields -
`Compact` is a plain pydantic `BaseModel`, so undeclared keys cannot reach the
payload. One hunk, `ServerInfo` only, five field declarations. Nothing else in
that file was touched. Flagging as an ownership deviation rather than assuming
consent.

**9. `out_of_scope_by_design` has 6 entries, not the 4 the brief listed.** The
brief's stated criterion was "the standing refusals, each with its reason, all
already written down in `endpoints.py` comments and `README.md`", and two more
meet it exactly: `talent/hr/cancel-opportunity` (dead code in the read build, no
live call site, and not the withdraw its name suggests) and `talent/recommendations`
(not a jobs feed - body `{key: "rnr", role}`, single caller is the profile
experience editor). Omitting known standing refusals from a block whose job is to
enumerate them seemed to be the disease being cured. **Trim to 4 if you disagree** -
they are two self-contained dict entries. No refusal was re-litigated; every
reason is quoted from what was already on disk.

**10. `EP_ACCOUNT_STATUS` is unbuilt (zero call sites) but sits under
`--- Reads ---`.** Left alone: unlike the Writes header, the Reads banner makes no
claim about what is built, so nothing there is false. Recording it so it is not
mistaken for a reachable route.

**11. The live `mcp__uplers__*` MCP process is STALE relative to disk** - it
reported `build.code.commit 9b65985d34f9` while disk HEAD is `883c786`. Every
verification in this slice was done with pytest and direct imports against disk,
never through the MCP tool. `mcp__uplers__uplers_server_info` will keep returning
the OLD five-key payload until the MCP host restarts the server.
