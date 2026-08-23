# Slice: the agent-surface read tools

Three READ-ONLY tools over the six agent-surface routes captured live 2026-08-23.
Built against the committed fixtures; **no live call was made from this slice.**

| | |
|---|---|
| Tools added | `uplers_email_scan`, `uplers_scanned_jobs`, `uplers_agent_settings` |
| Tool count | 47 -> **50** |
| Tests | 1251 -> **1343** (mine: **+52**; see "the other 40" below) |
| Full suite | **1343 passed, 0 failed, 43.65s** |
| Files written | `uplers_server/agent_surface.py` (new, 775 lines), `tests/test_agent_surface.py` (new, 52 tests), `uplers_server/endpoints.py` (+55, additive), `server.py` (+149, additive) |
| One file outside the four | `tests/test_tools.py` (+12/-5) - the registry census. See DEVIATION 1. |

---

## What each tool reports

### `uplers_email_scan()` - one request, `recommended-jobs-meta-email`

Scan on/off, consent grant time, last run, mailbox connected, job function, 79 jobs held,
per-board breakdown.

The docstring carries the consent finding: `has_consent` on this route is AUTHORITATIVE,
established by static analysis of the frontend bundle (`_slice-consent-semantics.md`, chunk
3474) - this is the route the UI re-reads the instant the consent write lands.
`get-outreach-dashboard-data -> consent_email_job_scan` is a downstream copy;
`interview-list -> meta.has_consent` is a DIFFERENT consent (the never-shipped interview scan).
The receipt ships in the tool output as `consent_authority`, so the claim travels with its
evidence rather than arriving as an assertion.

Both honesty requirements are implemented and tested:

* **Grant time survives as a timestamp.** `consent_email_job_scan` reads
  `"2026-08-12 01:32:36"` here and is surfaced as `scan.consent_granted_at`, never coerced.
  `bool("2026-08-12 01:32:36")` is `True` - the right answer for the wrong reason, and it
  would silently destroy the only record of when the scan was switched on.
* **Both counters ship; neither is picked.** `best_for_you_count: 50` against
  `best_for_you_breakdown` summing to **51**. Output carries `count`, `breakdown_total`,
  `counters_agree: false` and a `disagreements` entry naming both. Not averaged, not
  reconciled. The entry is computed, so a future payload where they agree drops it by itself.

### `uplers_scanned_jobs(best_for_you=None, limit=25)` - one request, `recommended-jobs-email`

Per row: title (`RequestForTalent`), company, `apply_url`, `job_board`, `publish_datetime`,
`best_for_you`. Plus `last_job_scan`, `breakdown` and `plan` - which on this route are
SIBLINGS of `data`, not children of it. A shaper that only read the unwrapped node would
silently report no scan time; asserted from both sides in
`test_the_envelope_metadata_lives_outside_data`.

`limit` truncates OUR output and says so in a note, because the route has no working limit of
its own. `total_rows` always reports the true 79.

**No fit score, and the emptiness was verified rather than trusted.** Measured over all 79 rows
of the fixture, independently of the shaper (`test_the_emptiness_the_no_score_rule_rests_on_is_real`):

| field | rows empty/null |
|---|---|
| `skills` (`[]`) | 79 / 79 |
| `city` (`""`) | 79 / 79 |
| `HR_Number` (`null`) | 79 / 79 |
| `enc_id` (`""`) | 79 / 79 |
| `description` (the placeholder, exactly one distinct value) | 79 / 79 |

Your summary was exact - nothing to report back differently. `NO_SCORE_REASON` ships in the
output. The emptiness counts (`rows_with_skills`, `rows_with_description`) are RE-DERIVED on
every call rather than quoted, so a route that starts sending real fields says so in its own
output instead of quietly disagreeing with a docstring - and still does not score.

### `uplers_agent_settings()` - four requests

Assembled headline from the captured account:

```
linkedin: follow-up is ON but no template exists on that channel.
auto-reply is OFF (8 categories configured, delay 2 hours).
16 companies are blocked for outreach; the agent skips them silently.
```

* **Follow-up** per channel: `disabled_followup_*` is INVERTED and the negation is done once,
  in the shaper; each channel also carries `source_field` with the raw Uplers name so the two
  can be checked against each other. Both channels enabled, interval 1 day.
* **Templates** per channel: existence + subject only. gmail exists, subject
  `"Looking to apply for {{title}} at {{company}}, need referral"`. linkedin is `""` - an empty
  template, which corroborates `outreach-step`'s `linkedin_connected: false` from a second
  route. **No body is ever returned, on any channel.**
* **Auto-reply**: `handle_auto_reply: false`, 2 hours, 8 categories including `asking_resume`.
  The note states the fact and attaches no recommendation; a test asserts the absence of
  imperative phrasing ("you should", "turn it on", "we recommend", ...).
* **Blocked companies**: 16 rows with `company_name`, `reason`, `created_at`. Docstring and a
  note both name `settings/companies` as a DIFFERENT route (alphabetical picker, paginated at
  20) that is not the blocklist. `test_the_two_routes_really_are_different_lists` measures the
  distinction off both fixtures rather than asserting it.

---

## The planted controls, and what each looked like red

Five guards were deliberately broken, watched fail, and restored. Suite green after each restore.

### 1. The no-fit-score guard - `"fit_score": 72` added to every shaped row

Three tests fired, including the tool-level sweep. Primary:

```
    for row in result["rows"]:
>       assert set(row) == ROW_KEYS, set(row) ^ ROW_KEYS
E       AssertionError: {'fit_score'}
E       Extra items in the left set: 'fit_score'
```

and the recursive numeric sweep, which catches a score-ish key carrying a NUMBER anywhere in
the result (booleans excluded, so `scored: False` is not self-incriminating):

```
E   AssertionError: assert [('$.rows[0]....t_score', 72)] == []
E     Left contains 2 more items, first extra item: ('$.rows[0].fit_score', 72)
```

### 2. The no-template-body guard - `"body": _text(body)` added to each channel

Three tests fired, including `test_the_tool_assembles_all_four_and_leaks_no_body` at the tool
layer. The control test plants a stand-in for the real PII and proves the sweep is capable of
finding it - necessary because the fixture MASKS the body, so a sweep run only against the
fixture could pass by having nothing to find:

```
    def test_the_body_sweep_can_actually_fire(self):
        secret = "I am currently serving a 60 day notice period at ACME"
>       assert not find_text(leaked, secret)
E       assert not True
E        +  where True = find_text({'route': 'talent/outreach/get-message-templates', ...},
E                                  'I am currently serving a 60 day notice period at ACME')
```

### 3. The follow-up inversion - `(not disabled)` replaced with `bool(disabled)`

Fired in BOTH directions, plus the assembled headline:

```
>       assert result["channels"][channel]["enabled"] is True
E       assert False is True                       # captured payload, both channels ON

>       assert result["channels"]["gmail"]["enabled"] is False
E       assert True is False                       # mutated payload, gmail disabled
```

### 4. Route exactness - `uplers_email_scan` pointed at its one-segment-away neighbour

Caught twice over. `unwrap`'s container check refused it before the census assertion was even
reached, which is defence in depth working:

```
E   uplers_server.outreach.OutreachError: talent/outreach/recommended-jobs-meta-email
    returned `data` as list, not dict. The captured shape for this route is dict and a
    different container means the route changed, not that it is empty.
```

### 5. Counter honesty - the shaper made to `max()` the two counters (the "obvious" fix)

```
E       assert 51 == 50
FAILED tests/test_agent_surface.py::TestEmailScan::test_both_counters_are_reported_and_neither_is_picked
```

Also standing, run at write time: narrowing `outreach.SUCCESS_VALUES` to one arm makes the
other arm's real fixtures stop reading (both directions), proving the string idiom on
`get-message-templates` and the integer idiom on the other five are each genuinely checked.

---

## DEVIATION 1 - I edited a fifth file: `tests/test_tools.py`

**Unavoidable, and flagged for your review.** Adding three tools makes the registry census red:

```
>       assert len(tools_listed) == 47
E       AssertionError: assert 50 == 47
```

That tripwire is designed to require a typed decision ("a further name appearing here is a
decision somebody had to type, not a drift"), so it fired correctly. Leaving it red would break
"do not leave a red suite"; deleting or skipping it was forbidden. The edit is +12/-5 and does
exactly four things: adds the three names to `AGENT_READ_TOOL_NAMES`, moves `47 -> 50` and
`4 -> 7`, and updates one comment sentence. **Every other tripwire in that census is untouched**
- `WRITE_TOOL_NAMES == 2`, `CONFIG_TOOL_NAMES == 1`, `PROFILE_WRITE_TOOL_NAMES == 2`, and no
`uplers_reauth`. The existing intersection assertion now automatically covers my three tools,
so they can never be filed into a write set without that line going red.

Revert with `git checkout tests/test_tools.py` if you would rather make this edit yourself.

## Three judgment calls inside the brief, cheap to reverse

1. **`gmail_email` is withheld.** The brief asked for "whether a mailbox is connected", which is
   what ships (`mailbox.connected`). The address itself is in the payload and is dropped, named
   in `withheld`, following the `outreach.WITHHELD_CONTACT_KEYS` precedent. Say the word and it
   goes in.
2. **The follow-up message bodies are withheld too.** You named the template body; `message_gmail`
   and `message_linkedin` are the same class of content on the follow-up route, so they get the
   same treatment. `message_withheld` reports whether one is set.
3. **`best_for_you=False` is REFUSED, not sent.** Only two modes were measured (unset -> 79,
   `true` -> 51). Rather than send an unmeasured value into a paid-product namespace, the
   refusal names the honest route to the same rows: fetch unset, which carries all 28 non-best
   rows, and filter locally. Follows the `saved_filter` precedent. If you would rather it sent
   `false`, that is a two-line change in `scanned_jobs_params`.

## Two things worth your attention

* **A third data point on the 50/51 disagreement.** The row-level count of
  `best_for_you: true` in `outreach_scanned_jobs.json` is **51**, which sides with the
  breakdown, not the scalar. I did NOT use this to pick a winner - `uplers_email_scan` reports
  only what its own route measured. It surfaces where it was measured, as
  `best_for_you_rows` on `uplers_scanned_jobs`. Your call whether that is enough to call 50 the
  stale counter.
* **`outreach.py`'s module docstring is now stale on consent.** It describes
  `consent_email_job_scan` vs `interview-list -> meta.has_consent` as an unresolved
  disagreement and says "neither pair is resolved here" - which was honest on the evidence it
  had. The bundle analysis resolves it. `outreach.py` is not my file so I did not touch it;
  `agent_surface.py` states the resolution and names outreach.py as holding the older position.

## The other 40 tests

Baseline 1251 -> 1343 is +92, and mine is +52. The remaining **+40** is
`tests/test_resume_write.py` (with `uplers_server/resume_write.py`), which landed in the tree
at 00:09 from a concurrent writer. Not mine, not touched. 1251 + 52 + 40 = 1343 exactly.

## Read-only, measured rather than asserted

`TestNothingHereWrites` is the first class in the test file. It asserts EXACT route lists per
tool (not merely "no writes"), because the dangerous mistake in this namespace is a GET to the
wrong sibling rather than a POST. Six requests across the three tools, zero non-GET. The
forbidden list covers `consent-email-job-scan`, `consent-auto-run`, `interview-feedback`,
`store-recommended-jobs`, `auto-run-request`, `intrested` and `settings/companies`. A static
sweep asserts the module contains no `post_json` / `post_form` / `delete_json` / `put_json`
anywhere, so a write helper cannot sit there waiting to be wired up. And
`test_the_census_can_actually_fail` proves the transport records a write when one happens -
`writes(calls) == []` is trivially true when no request was made at all.
