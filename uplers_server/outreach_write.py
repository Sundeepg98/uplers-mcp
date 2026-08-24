"""The four REVERSIBLE writes against the outreach agent's own settings.

This module is the write half of :mod:`uplers_server.agent_surface`, which
reads the same four surfaces. It exists because the agent he PAYS for is
configured entirely from Uplers' own screens today, and three of the four
settings can silently make that agent do less than he thinks it does - a dead
channel, a follow-up that never fires, a blocklist that removes companies from
every run.

**FOUR ROUTES ARE IN AND THE REST OF THE NAMESPACE IS OUT, on one criterion:
these four can be put back.** ``talent/outreach/*`` is where Uplers' paid
outreach product lives, and one path segment away sit
``store-employee-requests`` (the actual send, whose own UI copy says it cannot
be undone), ``reveal-email``, ``discard-job``, ``auto-run-request`` and the
five commercial claim routes. None of those is built, none has a constant, and
`endpoints.py` records them as prose beside these four so the line is visible
from the file whose job is to say what this server can reach.

**Nothing here can SEND THE WRITE.** ``profile_write`` states this as "nothing
here performs a request"; ``resume_write`` needed two reads to build a snapshot
and took the property one level in rather than dropping it, and this module
does the same. The orchestrators below read, and they are HANDED a ``send``
callable. With no sender they refuse - checked before anything is written and
before anything is snapshotted, so a call that could never have sent anything
leaves nothing behind.

**One honest limit on that seam, stated rather than hidden.** ``resume_write``
can say its route constant is named nowhere in the file. This one cannot, and
the reason is Uplers': ``settings/followup`` and ``settings/disabled-companies``
serve the GET and the POST on the SAME path string, so the constant this module
must name to read the record back is also the string a POST would use. What
remains structural is the sender, not the string - no constant here can put
anything on the wire, and the two genuinely new write paths
(``update-auto-reply``, ``store-message-template``) plus the DELETE template are
named only by `server.py`.

THE FIVE GUARDS, EVERY WRITE, NO EXCEPTIONS
-------------------------------------------
1.  **read-live.** The current record is read from its own GET before a body is
    built. Never from a fixture, never from a cache, never from what the caller
    remembers. On a route that sends its WHOLE record every time - and the
    follow-up route sends nine keys whether you touched them or not - building
    off a stale copy silently rewrites the eight fields you did not mean.
2.  **exact-body preview.** ``confirm=False`` returns the literal dict that
    would go on the wire, not a summary of it. The one departure is redaction
    of CARRIED-OVER personal text, described below; it is named in the result
    rather than done quietly.
3.  **snapshot-before.** The prior record is written to disk BEFORE the send,
    and the preview says how to get back. Ordering is the property, not
    existence: these are overwrite routes, so a snapshot taken afterwards
    records the new value and nothing recoverable.
4.  **empty-refusal.** A call that would change nothing raises
    :class:`WriteRefused` rather than sending a no-op. On an overwrite route a
    no-op write is not free - it is a full-record rewrite whose only effect is
    the chance to get one of the other eight fields wrong.
5.  **re-read-verify.** After a confirmed write the same GET is read again and
    the result says whether the value actually landed. **A 200 is not proof the
    value changed** - three of these four routes answer 200 and echo nothing
    useful, and the fourth answers with the string "success".

THE INVERSION TRAP, WHICH IS THE MOST DANGEROUS THING IN THIS FILE
-------------------------------------------------------------------
Uplers stores the follow-up switches INVERTED: ``disabled_followup_gmail:
false`` means the gmail channel is **ON**. Every public parameter here is
natural polarity (``gmail_enabled``, ``linkedin_enabled``) and the negation
happens in exactly ONE named place, :func:`to_disabled` (with
:func:`from_disabled` for the other direction). :func:`agent_surface.shape_followup_settings`
already does this negation once on the read side, and this is the same negation
in the same direction.

The failure it guards against is not a crash. A missing negation turns "keep
gmail on" into a request that switches it off, and a DOUBLE negation does the
same thing while looking correct at every individual site. Both directions are
pinned by tests, and so is the case that catches double-negation on a
pass-through: asking for a channel to stay ON must produce ``disabled_*:
False``.

PERSONAL TEXT: TWO CASES THAT LOOK THE SAME AND ARE NOT
--------------------------------------------------------
``gmail_template`` is a multi-paragraph self-description carrying employer
history, a LinkedIn URL and a notice period; ``message_gmail`` and
``message_linkedin`` on the follow-up route are the same kind of thing.
Everything in this repo that reads them reports that one EXISTS and what its
SUBJECT is, never the body - see ``agent_surface.WITHHELD_BODY_KEYS``. A tool
result ends up in a transcript, so that rule holds here too. But guard 2 says
the preview must show the exact body, and the body of these two routes IS that
text. The two are reconciled by asking where the text came from:

*   **Text the CALLER passed in is theirs, and is echoed verbatim** in the
    exact-body preview. That is the entire point of guard 2 - they are being
    asked to authorise sending exactly this, and a preview that hides what they
    typed is not a preview.
*   **Text CARRIED OVER from the live record is not**, and it is the case that
    exists only because these routes resend the whole record. Asking to change
    an interval would otherwise print his follow-up message back into the
    transcript as a side effect of a write about a number. Carried-over text
    renders as ``<carried over unchanged from Uplers: N chars, sha256 ...>``,
    the same treatment ``resume_write._describe_parts`` gives file bytes, and
    every redacted key is listed in ``body_redacted_keys`` so the omission is
    visible rather than silent.

The REAL body - the one with the real text in it - is what reaches the sender.
Only the returned copy is described.

WHAT THE SNAPSHOT IS FOR, AND WHY IT IS ON DISK
------------------------------------------------
Three of these four routes can be reversed by calling the same tool again with
the prior value, and for booleans, intervals, categories and company ids the
preview can simply print that value. The template write cannot: **there is no
delete-template route anywhere in Uplers' bundle**, the prior text is the only
way back, and the rule above forbids printing it. So the snapshot goes to disk
(``data/outreach_snapshots/``, gitignored) and the result hands back an id and
a path instead of the text. The same is true of a follow-up write that changes
a message.

All four snapshot, not just the two that need it. A uniform "every confirmed
write writes a restore point first" is one rule to keep true; "these two do" is
a question somebody has to re-answer every time the file is edited.

EVIDENCE
--------
Every wire fact here is VERIFIED against Uplers' production bundle by
``_audit/_slices/_slice-outreach-write-inventory.md`` - sections 3.3/3.4
(disabled companies), 3.7 (auto-reply), 5 (message templates) and 6 (follow-up
settings), each quoting its call site. Nothing in this file was derived from a
live probe: no write has been fired against his account by anything in this
wave.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from collections.abc import Iterable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import config, endpoints, policy
from .client import UplersError
from .outreach import unwrap

# The same guard class as both profile writes, not a fourth one. A caller that
# catches WriteRefused must catch every write in this server, and four classes
# all meaning "stopped before anything left the machine" is three too many.
from .profile_write import WriteRefused

# --- Read-back routes ------------------------------------------------------
#
# ALIASES, not definitions. endpoints.py is this server's single route
# authority. These four are the GETs that guard 1 reads and guard 5 re-reads;
# two of them double as the POST path (see the module docstring), which is
# Uplers' choice and is why the sender seam rather than the string is what
# makes "this module cannot write" true.

EP_READ_FOLLOWUP = endpoints.EP_OUTREACH_SETTINGS_FOLLOWUP
EP_READ_AUTO_REPLY = endpoints.EP_OUTREACH_AUTO_REPLY
EP_READ_TEMPLATES = endpoints.EP_OUTREACH_TEMPLATES
EP_READ_DISABLED_COMPANIES = endpoints.EP_OUTREACH_DISABLED_COMPANIES

# --- The follow-up route's shape -------------------------------------------

#: The body is a flat 9-key literal with NO spread - every key on every call,
#: including the ones the user did not touch. Spelled as a tuple so a key added
#: or dropped by a future edit fails a test loudly instead of quietly changing
#: what a write does. VERIFIED, slice section 6.
FOLLOWUP_BODY_KEYS = (
    "disabled_followup_gmail",
    "disabled_followup_linkedin",
    "interval_days",
    "interval_days_gmail",
    "interval_days_linkedin",
    "channel",
    "message",
    "message_gmail",
    "message_linkedin",
)

#: VERIFIED as a hardcoded literal at the only POST call site in 13.4 MB of
#: bundle. INFERRED, and NOT claimed: that the server accepts other values.
#: "gmail" and "linkedin" are guesses, so this client never sends one.
FOLLOWUP_CHANNEL = "both"

#: The legacy singular fields the GET falls back to. READ ONLY - the POST has
#: no `disabled_followup` key and no bare `interval_days` fallback, so these
#: names must never appear in an outgoing body. VERIFIED, slice section 6.
LEGACY_DISABLED_FIELD = "disabled_followup"
LEGACY_INTERVAL_FIELD = "interval_days"

#: Uplers' own client-side gate: a channel's follow-up message must contain
#: BOTH of these, unless that channel is disabled or its message is empty.
#: VERIFIED verbatim, slice section 6.
REQUIRED_MESSAGE_VARIABLES = ("{{outreachEmployee}}", "{{jobTitle}}")

#: How Uplers spells each channel in its own error text, so a refusal here
#: reads the same as a refusal there.
CHANNEL_LABELS = {"gmail": "Gmail", "linkedin": "LinkedIn"}

CHANNELS = ("gmail", "linkedin")

# --- The template route's shape --------------------------------------------

#: **`provider` IS A NUMBER.** VERIFIED three ways in the bundle: the
#: declaration `oe=1,ie=2`, the response demux `c===ie?r.gmail_message_id=u`,
#: and an independent call site carrying the literal `provider:2`. Passing the
#: string "gmail" would be a different call, not a synonym, so the friendly
#: name is mapped to the integer in exactly one place, :func:`provider_for`.
PROVIDER_LINKEDIN = 1
PROVIDER_GMAIL = 2
PROVIDERS = {"linkedin": PROVIDER_LINKEDIN, "gmail": PROVIDER_GMAIL}

#: Exactly three keys, ONE CHANNEL PER CALL. This is Path B, the template
#: editor, VERIFIED at all 6 of its call sites.
#:
#: PATH A EXISTS AND IS NOT BUILT. The preview screen POSTs the same route with
#: a FOURTH key, `tag: "rewrite-message-from-preview"`, and reads the response
#: as `res.data.template_id` rather than `res.data.status`. That id is then fed
#: to `auto-run-request` / `account/outreach-agent` - it is the seam that ties
#: the preview screen to the SEND. Path B is the plain "save my template"
#: write and is the only one in scope here; the divergence is recorded so a
#: later reader does not "fix" this body by adding the missing key.
TEMPLATE_BODY_KEYS = ("message_template", "message_subject", "provider")

# --- The auto-reply route's shape ------------------------------------------

AUTO_REPLY_BODY_KEYS = ("hours", "handle_auto_reply", "auto_reply_categories")

#: MEASURED in `tests/fixtures/outreach_auto_reply.json` - the 8 categories his
#: account carries. **NOT a whitelist.** An unknown category is not rejected
#: (this list is one capture, not Uplers' enum), but it IS reported in the
#: preview, so a typo is visible before anybody confirms rather than arriving
#: as a silently-ignored category or a 422.
KNOWN_AUTO_REPLY_CATEGORIES = (
    "asking_talent_info",
    "asking_email_source",
    "direct_apply",
    "asking_resume",
    "asking_job_details",
    "asking_to_connect",
    "asking_confirmation",
    "complete_assessment",
)

#: Uplers' own refusal text, quoted. VERIFIED, slice section 3.7.
AUTO_REPLY_EMPTY_CATEGORIES_ERROR = (
    "Select at least one category to enable auto-reply"
)

# --- Personal text ---------------------------------------------------------

#: Body keys whose value is personal text. A value the CALLER supplied for one
#: of these is echoed; a value CARRIED OVER from the live record is described
#: instead. See the module docstring - the difference is provenance, not the
#: key. Kept in step with `agent_surface.WITHHELD_BODY_KEYS`, which withholds
#: the same fields on the read side.
PERSONAL_BODY_KEYS = (
    "message",
    "message_gmail",
    "message_linkedin",
    "message_template",
)

#: Same shape and same reason as `profile_write.SNAPSHOT_ID_RE` and
#: `resume_write.SNAPSHOT_ID_RE`: a restore point is loaded by an id that
#: arrives from an agent-callable tool, so an id this server did not write is
#: refused before anything on disk is opened.
SNAPSHOT_ID_RE = re.compile(r"[0-9]{1,20}-[a-z0-9-]{1,40}")


class OutreachWriteRefused(WriteRefused):
    """A settings write stopped before anything left the machine.

    Subclasses the shared :class:`~uplers_server.profile_write.WriteRefused`
    rather than replacing it, so every existing handler already catches it
    while a caller that wants to tell an outreach refusal from a profile one
    still can.
    """

    kind = "outreach_write_refused"


def snapshots_dir() -> Path:
    """Its own directory, beside the other two and deliberately not inside one.

    `uplers_list_profile_snapshots` globs `profile_snapshots/` and refuses any
    record with no skills in it; `resume_snapshots/` holds file bytes. A
    settings record filed in either would list as a zero-skill row and refuse
    on restore - a confusing near-miss rather than a clean separation.
    """
    path = config.DATA_DIR / "outreach_snapshots"
    path.mkdir(parents=True, exist_ok=True)
    return path


# ===========================================================================
# The inversion, in one place
# ===========================================================================


def to_disabled(enabled: Any) -> bool:
    """Natural polarity -> Uplers' polarity. **THE ONLY NEGATION IN THIS FILE.**

    ``gmail_enabled=True`` means he wants follow-ups sent on gmail, and Uplers
    records that as ``disabled_followup_gmail: false``. Every outgoing body
    builds its two flags through this function and nothing else negates.

    A SECOND negation anywhere - even a correct-looking one at a call site -
    cancels this one and produces a request that switches OFF the channel the
    caller asked to switch ON, with no error at any point. That is why the
    negation is a named function with a test on both directions rather than a
    `not` at the site that needs it.
    """
    return not bool(enabled)


def from_disabled(disabled: Any) -> bool | None:
    """Uplers' polarity -> natural polarity. Tri-state: ``None`` means unsaid.

    ``None`` is not ``False``. A payload that did not carry the field has not
    told us the channel is off, and defaulting it to off would make a read say
    something the server never said. Callers that need a value for the wire
    resolve the ``None`` explicitly, where the defaulting is visible.
    """
    if disabled is None:
        return None
    return not bool(disabled)


def clamp_interval(value: Any) -> int:
    """Uplers' own client-side clamp, mirrored: ``t = e > 0 ? e : 1``.

    VERIFIED at both the GET seed and the POST body. Mirrored rather than
    improved on: a client stricter than theirs refuses values the platform
    would take, and a looser one turns a legible local refusal into a remote
    422. Anything that is not an integer is refused rather than coerced - a
    silent ``int("3 days") -> ValueError`` would surface as a stack trace from
    inside a write.
    """
    if isinstance(value, bool) or not isinstance(value, int):
        try:
            value = int(str(value).strip())
        except (TypeError, ValueError):
            raise OutreachWriteRefused(
                "%r is not a number of days. Uplers stores this as an integer and "
                "clamps it to at least 1. Nothing was sent." % (value,)
            ) from None
    return value if value > 0 else 1


def as_int(value: Any, *, field: str) -> int:
    """An integer for the wire, with NO range gate invented.

    Deliberately not :func:`clamp_interval`. That function mirrors a clamp
    Uplers' own client runs (``e > 0 ? e : 1``) on the three follow-up
    intervals. The auto-reply route's ``hours`` passes through a minified
    coercion (``hours: Ge(t.hours)``) whose identity was NOT resolved from the
    bundle, so no floor is claimed for it here: a client guard stricter than
    the server's refuses values the platform would take, and inventing one on
    unresolved evidence is exactly the guess this codebase does not make.
    """
    if isinstance(value, bool) or not isinstance(value, int):
        try:
            value = int(str(value).strip())
        except (TypeError, ValueError):
            raise OutreachWriteRefused(
                "%r is not a whole number, and %s goes on the wire as one. Nothing "
                "was sent." % (value, field)
            ) from None
    return value


def provider_for(channel: Any) -> int:
    """Friendly channel name -> Uplers' integer. The ONLY place that maps it.

    1 = LinkedIn, 2 = Gmail, VERIFIED three ways in the bundle. A caller says
    "gmail"; the wire gets ``2``. Sending the string would be a different call
    to the same route, and this API answers 200 to more than one shape.
    """
    key = str(channel or "").strip().lower()
    if key not in PROVIDERS:
        raise OutreachWriteRefused(
            "%r is not a channel. Uplers has exactly two on this route, %s, and "
            "sends them as the integers %s. Nothing was sent."
            % (
                str(channel)[:40],
                " and ".join(sorted(PROVIDERS)),
                ", ".join("%s=%d" % (name, PROVIDERS[name]) for name in sorted(PROVIDERS)),
            )
        )
    return PROVIDERS[key]


# ===========================================================================
# Reading the live record
# ===========================================================================


def read_followup(payload: Any) -> dict:
    """The current follow-up record, with Uplers' own legacy fallbacks applied.

    VERIFIED at the GET arm: it falls back from ``disabled_followup_gmail`` /
    ``disabled_followup_linkedin`` to a singular legacy ``disabled_followup``,
    and from ``interval_days_gmail`` / ``interval_days_linkedin`` to
    ``interval_days``. The server may still answer with the older single-channel
    shape, so the fallback is mirrored here - and ONLY here. **The POST never
    sends the singular field**; there is no ``disabled_followup`` key in the
    body at all, which is why the fallback lives in the reader rather than in
    the record it returns.

    Values are returned in UPLERS' polarity, not natural polarity. This is a
    reader of their record; the flip happens once, at the body builder.
    """
    data = unwrap(payload, route=EP_READ_FOLLOWUP, expect=dict)

    legacy_disabled = data.get(LEGACY_DISABLED_FIELD)
    legacy_interval = data.get(LEGACY_INTERVAL_FIELD)

    record: dict = {}
    for channel in CHANNELS:
        disabled = data.get("disabled_followup_%s" % channel)
        if disabled is None:
            disabled = legacy_disabled
        record["disabled_followup_%s" % channel] = bool(disabled)

        interval = data.get("interval_days_%s" % channel)
        if interval is None:
            interval = legacy_interval
        record["interval_days_%s" % channel] = clamp_interval(
            1 if interval is None else interval
        )

        message = data.get("message_%s" % channel)
        record["message_%s" % channel] = message if message else None

    # The singular pair. `interval_days` seeds to 1 when absent, exactly as
    # their GET does (`k(x.interval_days ?? 1)`); `message` has no seed at all,
    # so an absent one reaches the body as null via `R.message || null`.
    record[LEGACY_INTERVAL_FIELD] = clamp_interval(
        1 if legacy_interval is None else legacy_interval
    )
    record["message"] = data.get("message") or None
    return record


def read_auto_reply(payload: Any) -> dict:
    """The current auto-reply record: the switch, the delay and the categories."""
    data = unwrap(payload, route=EP_READ_AUTO_REPLY, expect=dict)
    raw = data.get("auto_reply_categories")
    return {
        "hours": data.get("hours"),
        "handle_auto_reply": bool(data.get("handle_auto_reply")),
        "auto_reply_categories": [
            str(item) for item in raw if isinstance(item, str) and item.strip()
        ]
        if isinstance(raw, list)
        else [],
    }


def read_templates(payload: Any) -> dict:
    """Both channels' templates, BODIES INCLUDED. Handle the return value.

    This is the one reader in this repo that keeps the template body, and it
    keeps it for exactly one reason: there is no delete-template route, so a
    copy taken before the write is the only rollback that can exist. It goes to
    disk, in a snapshot; it does not go into a preview, a result or any tool
    response. :func:`describe_personal` is what a caller renders it through.
    """
    data = unwrap(payload, route=EP_READ_TEMPLATES, expect=dict)
    record: dict = {}
    for channel in CHANNELS:
        record[channel] = {
            "message_template": data.get("%s_template" % channel) or "",
            "message_subject": data.get("%s_template_subject" % channel) or "",
        }
    return record


def read_blocklist(payload: Any) -> list[dict]:
    """The real blocklist, as ``{id, company_id, company_name}`` rows.

    **NOT read off ``talent/outreach/settings/companies``.** That route is the
    alphabetical company PICKER, paginated at 20 rows, where `IsActive` marks a
    chosen row - reading a blocklist off it would report the first twenty
    companies in the alphabet as blocked. `endpoints.py` records the trap and
    deliberately gives that route no constant.

    **THE TWO IDS ARE NOT INTERCHANGEABLE.** ``id`` is the blocklist ROW and is
    what the DELETE takes as a path segment; ``company_id`` is the company and
    is what the POST body carries. Both are small integers and swapping them
    unblocks the wrong company or nothing at all, with a 200 either way, so
    both are carried on every row and the two writes take them from different
    fields on purpose.
    """
    rows_raw = unwrap(payload, route=EP_READ_DISABLED_COMPANIES, expect=list)
    rows: list[dict] = []
    for raw in rows_raw:
        if not isinstance(raw, dict):
            continue
        rows.append(
            {
                "id": raw.get("id"),
                "company_id": raw.get("company_id"),
                "company_name": raw.get("company_name") or None,
            }
        )
    return rows


# ===========================================================================
# Rendering: what a preview may and may not carry
# ===========================================================================


def describe_personal(value: Any) -> str:
    """Personal text, as a reader can check it, WITHOUT the text.

    The same treatment ``resume_write._describe_parts`` gives file bytes, and
    for the same reason: a preview must show the SHAPE - that a message is
    there, how long it is, that it is the one already on the account - and must
    not carry the content back through a tool response into a transcript. The
    sha256 prefix is what makes "unchanged" checkable: two previews of the same
    carried-over message render identically, and an edited one does not.
    """
    text = "" if value is None else str(value)
    if not text:
        return "<carried over unchanged from Uplers: empty>"
    return "<carried over unchanged from Uplers: %d chars, sha256 %s>" % (
        len(text),
        hashlib.sha256(text.encode("utf-8")).hexdigest()[:16],
    )


def render_body(body: dict, carried_over: Iterable[str]) -> tuple[dict, list[str]]:
    """``(body as it may be printed, keys that were redacted)``.

    Provenance is the whole rule and it arrives as ``carried_over``, computed by
    the orchestrator that knows which values the caller supplied. A personal
    key the CALLER set is echoed verbatim - guard 2 exists so they can check
    exactly what they are authorising. A personal key carried over from the
    live record is described instead.

    Non-personal keys are never touched, whatever their provenance: an interval
    or a boolean carried over from the record is not personal data and hiding
    it would break the exact-body preview for nothing.
    """
    carried = set(carried_over)
    shown: dict = {}
    redacted: list[str] = []
    for key, value in body.items():
        if key in PERSONAL_BODY_KEYS and key in carried and value:
            shown[key] = describe_personal(value)
            redacted.append(key)
        else:
            shown[key] = value
    return shown, redacted


def diff_of(current: dict, new: dict, *, ignore: Iterable[str] = ()) -> list[dict]:
    """``[{field, from, to}]`` for every key whose value would change.

    Guard 4 is decided on this list being empty, and the list is also what the
    preview shows a reader instead of asking them to compare two dicts by eye.

    PERSONAL KEYS APPEAR WITHOUT THEIR VALUES. A diff row for a message would
    print both the old text and the new one, which is the leak this module
    spends the most effort avoiding; those rows carry ``changed: True`` and the
    two lengths instead, which is what a reader needs to answer "am I about to
    overwrite something".
    """
    skip = set(ignore)
    changes: list[dict] = []
    for key in new:
        if key in skip:
            continue
        before = current.get(key)
        after = new[key]
        if before == after:
            continue
        if key in PERSONAL_BODY_KEYS:
            changes.append(
                {
                    "field": key,
                    "changed": True,
                    "from_length": len(str(before)) if before else 0,
                    "to_length": len(str(after)) if after else 0,
                    "values_withheld": (
                        "both texts are personal and are not printed; the "
                        "lengths say whether something is being overwritten"
                    ),
                }
            )
        else:
            changes.append({"field": key, "from": before, "to": after})
    return changes


def stamp_to_iso(stamp: Any) -> str | None:
    """Snapshot timestamps are unix floats on disk; a reader wants a date."""
    if stamp is None:
        return None
    try:
        return datetime.fromtimestamp(float(stamp), timezone.utc).isoformat(
            timespec="seconds"
        )
    except (OSError, OverflowError, ValueError, TypeError):
        return None


# ===========================================================================
# Snapshots
# ===========================================================================


def write_snapshot(record: Any, *, kind: str, label: str = "auto") -> dict:
    """Persist the PRIOR record. ALWAYS before a write, never after.

    Ordering is the property, not existence. Every route here overwrites, and
    every read-back GET returns whatever is current - so a snapshot taken after
    the write records the new value and nothing recoverable. For the template
    write that is not a degraded rollback, it is no rollback: Uplers has no
    delete-template route and no history.

    The record is written and READ BACK before the function returns, so a
    snapshot that exists is a snapshot that is really on disk. A short write, a
    full disk or a sync-on-close failure all produce a file that exists and is
    wrong, and "the file exists" is the exact claim a precondition must not
    accept.

    **The returned dict never carries the record.** It carries the id, the
    relativised path and a count. The file holds the personal text; the return
    value is what ends up in a transcript, and those are different places.
    """
    clean_kind = re.sub(r"[^a-z0-9-]+", "-", str(kind).lower()).strip("-") or "outreach"
    clean_label = re.sub(r"[^a-z0-9-]+", "-", str(label).lower()).strip("-") or "auto"
    snapshot_id = "%d-%s-%s" % (int(time.time()), clean_kind[:20], clean_label[:20])
    directory = snapshots_dir()
    path = directory / ("%s.json" % snapshot_id)

    payload = {
        "snapshot_id": snapshot_id,
        "taken_at": time.time(),
        "kind": clean_kind,
        "label": clean_label,
        "record": record,
    }
    text = json.dumps(payload, indent=2, ensure_ascii=False)
    try:
        path.write_text(text, encoding="utf-8")
        written = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise OutreachWriteRefused(
            policy.relativise_paths(
                "The snapshot could not be written to disk (%s), so there would be "
                "no record of what this setting held before the write. Nothing was "
                "sent." % exc,
                (path, directory),
            )
        ) from exc

    if written != text:
        raise OutreachWriteRefused(
            policy.relativise_paths(
                "The snapshot read back as %d characters, not the %d that were "
                "written, so the copy on disk is not the record. Nothing was sent."
                % (len(written), len(text)),
                (path,),
            )
        )

    return {
        "snapshot_id": snapshot_id,
        "kind": clean_kind,
        "taken_at": payload["taken_at"],
        "taken_at_iso": stamp_to_iso(payload["taken_at"]),
        # Relativised, not dropped - the same trade the other two snapshot
        # writers make, and for the same reason: this path IS the undo handle
        # for the template write and the operator is expected to open it. See
        # policy.display_path.
        "path": policy.display_path(str(path)),
    }


def list_snapshots() -> list[dict]:
    """Newest first, and never the records themselves.

    One unreadable file must not hide the rest: listing is a read, and an
    operator hunting for a restore point after a bad write is the worst
    possible moment for the list to raise.
    """
    out: list[dict] = []
    for path in sorted(snapshots_dir().glob("*.json"), reverse=True):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(data, dict):
            continue
        out.append(
            {
                "snapshot_id": data.get("snapshot_id", path.stem),
                "kind": data.get("kind"),
                "label": data.get("label"),
                "taken_at": data.get("taken_at"),
                "taken_at_iso": stamp_to_iso(data.get("taken_at")),
            }
        )
    return out


def load_snapshot(snapshot_id: Any) -> dict:
    """A restore point AND ITS RECORD - which for a template is his own text.

    The three guards are the siblings', in the siblings' order, and for the
    siblings' reason: in the Instahyre server the version without them resolved
    ``"../not-a-snapshot"`` to a file outside the directory and "restored" it
    over real data. The id is validated BEFORE the directory is touched;
    ordering it the other way makes the containment guard conditional on the
    directory being non-empty, and a check that only runs in some directory
    states is not a check.

    **The caller receives personal text.** That is the point - restoring a
    template means passing the prior body back into
    :func:`set_message_template`, where it becomes caller-supplied text and is
    echoed in the preview like any other caller-supplied text. It must not be
    printed anywhere else.
    """
    if not SNAPSHOT_ID_RE.fullmatch(str(snapshot_id or "")):
        raise OutreachWriteRefused(
            "%r is not a snapshot id. Ids look like "
            "'1755780000-template-pre-write'." % str(snapshot_id)[:60]
        )

    directory = snapshots_dir().resolve()
    path = (directory / ("%s.json" % snapshot_id)).resolve()
    # Behind the pattern check rather than instead of it: if the pattern is ever
    # loosened, a path that escaped the directory still dies here.
    if path.parent != directory:
        raise OutreachWriteRefused(
            "Refusing to read a snapshot from outside the snapshots directory."
        )
    if not path.is_file():
        raise OutreachWriteRefused(
            "No outreach snapshot %r." % str(snapshot_id)[:60]
        )

    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        # The message is composed around an exception whose filename this server
        # never looks inside; OSError renders it through repr(), so both
        # spellings are scrubbed. Same site as profile_write.load_snapshot.
        raise OutreachWriteRefused(
            policy.relativise_paths(
                "Outreach snapshot %s could not be read as JSON (%s). Refusing to "
                "restore from a file this server cannot understand."
                % (path.name, exc),
                (path, directory),
            )
        ) from exc

    if not isinstance(record, dict) or "record" not in record:
        raise OutreachWriteRefused(
            "Outreach snapshot %s is not a record this server wrote. Refusing."
            % path.name
        )
    out = dict(record)
    out["taken_at_iso"] = stamp_to_iso(record.get("taken_at"))
    out["path"] = policy.display_path(str(path))
    return out


# ===========================================================================
# The sender seam
# ===========================================================================


def json_sender_for(client: Any, path: str):
    """The one callable that can POST one of these bodies. Built by `server.py`.

    The seam that makes "no write happened" a STRUCTURAL claim rather than an
    observational one. The orchestrators cannot send without one of these, so a
    test proving the sender was never called proves something about control
    flow, not about what a mock transport happened to see.

    `path` is attached to the returned callable so a preview can print the
    endpoint it would hit without this module holding the constant.
    """

    async def send(body):
        return await client.post_json(path, dict(body or {}))

    send.path = path
    send.method = "POST application/json"
    return send


def delete_sender_for(client: Any, path_template: str):
    """The DELETE half of the blocklist pair. Takes the ROW id, not a body.

    **The template must carry ``{id}`` and this refuses one that does not.**
    That is not defensive noise: the collection URL and the item URL differ by
    one path segment, both exist, and a sender built from the collection
    constant by a copy-paste would issue ``DELETE`` at the whole collection.
    Refusing at construction means such a sender cannot be built at all, which
    is a stronger guarantee than checking at send time.

    ``TalentClient`` has no ``delete`` verb - it has get_json, post_json and
    post_form and nothing else - so this reaches for the client's own request
    path directly, exactly as ``resume_write.sender_for`` does for multipart.
    **The clean home for this is a `delete_json` verb on `TalentClient`**; that
    edit was out of scope for the wave that wrote this file.
    """
    if "{id}" not in str(path_template):
        raise OutreachWriteRefused(
            "A blocklist DELETE sender was built from %r, which carries no {id} "
            "placeholder. That path is the COLLECTION, and a DELETE aimed at it "
            "is not an unblock. Refusing to build the sender at all."
            % str(path_template)[:80]
        )

    async def send(row_id):
        return await client._request("DELETE", str(path_template).format(id=row_id))

    send.path = path_template
    send.method = "DELETE"
    return send


def _endpoint_of(send: Any) -> str | None:
    return getattr(send, "path", None)


def _method_of(send: Any, default: str) -> str:
    return getattr(send, "method", None) or default


def _require_sender(send: Any) -> None:
    if send is None or not callable(send):
        raise OutreachWriteRefused(
            "This write was called with no sender, so there is nothing it could put "
            "on the wire. That is deliberate: these writes are built so they cannot "
            "fire without the caller supplying the route. Nothing was sent."
        )


# ===========================================================================
# Guard 5: re-read and say whether it landed
# ===========================================================================


async def _verify(client: Any, *, route: str, reader, expected: dict) -> dict:
    """Re-read the same GET and check the values that were supposed to change.

    **A 200 IS NOT PROOF THE VALUE CHANGED.** Three of these four routes answer
    ``{"status": 200}`` and echo nothing a caller can check; the fourth answers
    the string "success". So the only honest evidence that a write landed is
    the record itself, read again.

    A failure HERE must not raise. The write already happened, and turning a
    failed verification into an exception would throw away the one fact the
    caller most needs - that something was sent. So the read is caught and
    reported as ``re_read: False`` with the reason, which reads as "unknown",
    never as "landed".

    Personal values are compared but never printed: a mismatch row says which
    field disagreed and how long each side was.
    """
    try:
        payload = await client.get_json(route)
        current = reader(payload)
    except UplersError as exc:
        return {
            "re_read": False,
            "landed": None,
            "route": route,
            "error": "%s: %s" % (type(exc).__name__, exc),
            "note": (
                "The write was sent and the read-back failed, so whether it landed "
                "is UNKNOWN - not 'no'. Re-read the settings to find out."
            ),
        }

    mismatches = []
    for key, wanted in expected.items():
        actual = current.get(key)
        if actual == wanted:
            continue
        if key in PERSONAL_BODY_KEYS:
            mismatches.append(
                {
                    "field": key,
                    "expected_length": len(str(wanted)) if wanted else 0,
                    "actual_length": len(str(actual)) if actual else 0,
                    "values_withheld": "both texts are personal and are not printed",
                }
            )
        else:
            mismatches.append({"field": key, "expected": wanted, "actual": actual})

    return {
        "re_read": True,
        "landed": not mismatches,
        "route": route,
        "checked": sorted(expected),
        "mismatches": mismatches,
        "note": (
            "Verified by reading the record back, not by the write's own status - "
            "these routes answer 200 whether or not the value moved."
        )
        if not mismatches
        else (
            "THE WRITE DID NOT LAND as asked. The route accepted the request and "
            "the record still disagrees on the fields listed."
        ),
    }


# ===========================================================================
# A. Follow-up settings
# ===========================================================================


def check_message_variables(channel: str, message: Any, *, enabled: bool) -> None:
    """Uplers' own gate, mirrored including BOTH its exemptions.

    A channel's follow-up message must contain both ``{{outreachEmployee}}``
    and ``{{jobTitle}}`` - UNLESS that channel is disabled, or its message is
    empty. VERIFIED verbatim in the bundle (slice section 6); the error text
    below is theirs, so a refusal here reads the same as a refusal there.

    Both exemptions are real branches, not sloppiness: a disabled channel sends
    nothing, and an empty message means "use whatever default Uplers has",
    which is a state their own UI allows and this must not make unreachable.
    """
    if not enabled:
        return
    text = (message or "").strip() if isinstance(message, str) else ""
    if not text:
        return
    label = CHANNEL_LABELS.get(channel, channel)
    for variable in REQUIRED_MESSAGE_VARIABLES:
        if variable not in text:
            raise OutreachWriteRefused(
                "%s: The follow-up message must include the %s variable. Uplers' "
                "own editor refuses this before sending and so does this. Nothing "
                "was sent." % (label, variable)
            )


def followup_body(
    current: dict,
    *,
    gmail_enabled: Any = None,
    linkedin_enabled: Any = None,
    gmail_interval_days: Any = None,
    linkedin_interval_days: Any = None,
    interval_days: Any = None,
    gmail_message: Any = None,
    linkedin_message: Any = None,
    message: Any = None,
) -> tuple[dict, set[str]]:
    """``(the exact 9-key body, the set of keys carried over)``.

    ``None`` for any parameter means "leave it as Uplers has it", which is the
    only safe default on a route that resends the WHOLE record: the alternative
    is a body that quietly zeroes every field the caller did not mention.

    The body is built as a flat literal in the bundle's own key order, with no
    spread and no merge, so there is no parameter through which a tenth key
    could arrive. ``channel`` is the hardcoded ``"both"``; the two flags go
    through :func:`to_disabled` and nothing else negates.
    """
    carried: set[str] = set()

    wanted_enabled: dict[str, bool] = {}
    for channel, requested in (
        ("gmail", gmail_enabled),
        ("linkedin", linkedin_enabled),
    ):
        if requested is None:
            live = from_disabled(current.get("disabled_followup_%s" % channel))
            wanted_enabled[channel] = bool(live)
            carried.add("disabled_followup_%s" % channel)
        else:
            wanted_enabled[channel] = bool(requested)

    intervals: dict[str, int] = {}
    for channel, requested in (
        ("gmail", gmail_interval_days),
        ("linkedin", linkedin_interval_days),
    ):
        key = "interval_days_%s" % channel
        if requested is None:
            intervals[channel] = clamp_interval(current.get(key))
            carried.add(key)
        else:
            intervals[channel] = clamp_interval(requested)

    if interval_days is None:
        singular_interval = clamp_interval(current.get(LEGACY_INTERVAL_FIELD))
        carried.add(LEGACY_INTERVAL_FIELD)
    else:
        singular_interval = clamp_interval(interval_days)

    messages: dict[str, Any] = {}
    for channel, requested in (
        ("gmail", gmail_message),
        ("linkedin", linkedin_message),
    ):
        key = "message_%s" % channel
        if requested is None:
            messages[channel] = current.get(key) or None
            carried.add(key)
        else:
            # `R.message_x || null` - the empty string reaches the wire as null,
            # which is how their own client clears a message.
            messages[channel] = requested or None

    if message is None:
        singular_message = current.get("message") or None
        carried.add("message")
    else:
        singular_message = message or None

    for channel in CHANNELS:
        check_message_variables(
            channel, messages[channel], enabled=wanted_enabled[channel]
        )

    body = {
        "disabled_followup_gmail": to_disabled(wanted_enabled["gmail"]),
        "disabled_followup_linkedin": to_disabled(wanted_enabled["linkedin"]),
        "interval_days": singular_interval,
        "interval_days_gmail": intervals["gmail"],
        "interval_days_linkedin": intervals["linkedin"],
        "channel": FOLLOWUP_CHANNEL,
        "message": singular_message,
        "message_gmail": messages["gmail"],
        "message_linkedin": messages["linkedin"],
    }
    return body, carried


async def set_followup(
    client: Any,
    *,
    gmail_enabled: Any = None,
    linkedin_enabled: Any = None,
    gmail_interval_days: Any = None,
    linkedin_interval_days: Any = None,
    interval_days: Any = None,
    gmail_message: Any = None,
    linkedin_message: Any = None,
    message: Any = None,
    confirm: bool = False,
    send: Any = None,
) -> dict:
    """Whether an unanswered reply gets chased, and how often. Reversible.

    The order of the steps IS the safety design:

    1.  Read the CURRENT record (guard 1). Nothing is built off a cached value,
        because eight of the nine keys will be resent from it.
    2.  Build the exact body and run Uplers' own two gates. A rejected message
        costs zero requests.
    3.  Refuse if nothing would change (guard 4). On a whole-record overwrite a
        no-op is not free - it is a rewrite whose only possible effect is
        getting one of the untouched fields wrong.
    4.  If `confirm` is False, return the preview (guard 2) and send nothing.
    5.  Snapshot the prior record to disk (guard 3), then send.
    6.  Re-read and say whether it landed (guard 5).
    """
    payload = await client.get_json(EP_READ_FOLLOWUP)
    current = read_followup(payload)

    body, carried = followup_body(
        current,
        gmail_enabled=gmail_enabled,
        linkedin_enabled=linkedin_enabled,
        gmail_interval_days=gmail_interval_days,
        linkedin_interval_days=linkedin_interval_days,
        interval_days=interval_days,
        gmail_message=gmail_message,
        linkedin_message=linkedin_message,
        message=message,
    )
    # What the record would produce with nothing asked for. Comparing against
    # THIS rather than against the raw record is what makes "would change
    # nothing" mean the same thing on both sides of the clamp: a stored 0 and a
    # requested 0 both render as 1, so they compare equal and the call refuses
    # instead of sending a rewrite the caller did not ask for.
    baseline, _ = followup_body(current)
    changes = diff_of(baseline, body, ignore=("channel",))

    if not changes:
        raise OutreachWriteRefused(
            "Nothing would change: the follow-up settings already hold every value "
            "you named. This route rewrites the WHOLE record on every call - all "
            "nine keys, including the ones you did not mention - so re-sending it "
            "for no change is a rewrite with no benefit and one more chance to get "
            "an untouched field wrong. Nothing was sent."
        )

    shown_body, redacted = render_body(body, carried)
    common = {
        "action": "set_followup",
        "method": _method_of(send, "POST application/json"),
        "endpoint": _endpoint_of(send),
        "body": shown_body,
        "body_redacted_keys": redacted,
        "body_keys": sorted(body),
        "changes": changes,
        "reversible": True,
        "current": {
            "gmail_enabled": from_disabled(current.get("disabled_followup_gmail")),
            "linkedin_enabled": from_disabled(
                current.get("disabled_followup_linkedin")
            ),
            "interval_days_gmail": current.get("interval_days_gmail"),
            "interval_days_linkedin": current.get("interval_days_linkedin"),
            "gmail_message_set": bool(current.get("message_gmail")),
            "linkedin_message_set": bool(current.get("message_linkedin")),
        },
        "notes": [
            "Uplers stores these switches INVERTED, as disabled_followup_<channel>. "
            "The parameters here are natural polarity and the negation happens once, "
            "in outreach_write.to_disabled - so `gmail_enabled=True` is "
            "`disabled_followup_gmail: false` on the wire, which is what the body "
            "above shows.",
            "All nine keys go on every call. That is Uplers' own client's shape, not "
            "a choice made here: their POST is a flat literal with no spread, so a "
            "partial body would exercise a path their UI never exercises.",
            "channel is the hardcoded literal 'both'. It is the only value at the "
            "only call site in their bundle; 'gmail' and 'linkedin' are guesses and "
            "are not sent.",
        ],
    }
    if redacted:
        common["notes"].append(
            "%s are being resent UNCHANGED from your account and are shown as a "
            "length and a checksum rather than as text. Follow-up message bodies "
            "are personal and a tool result ends up in a transcript. Text YOU pass "
            "in is echoed in full - that is what the preview is for."
            % ", ".join(sorted(redacted))
        )

    if not confirm:
        result = dict(common)
        result["performed"] = False
        result["snapshot"] = {"written": False}
        result["to_confirm"] = "uplers_set_followup(..., confirm=True)"
        result["notes"].insert(
            0,
            "PREVIEW - nothing was sent and no snapshot was written. Confirming "
            "writes the current record to disk first, then sends, then reads the "
            "record back to check the change actually landed.",
        )
        return result

    _require_sender(send)
    snapshot = write_snapshot(current, kind="followup", label="pre-write")

    response = await send(body)

    verification = await _verify(
        client,
        route=EP_READ_FOLLOWUP,
        reader=read_followup,
        expected={key: body[key] for key in body if key != "channel"},
    )

    result = dict(common)
    result["performed"] = True
    result["snapshot"] = dict(snapshot, written=True)
    result["response"] = response if isinstance(response, dict) else {}
    result["verified"] = verification
    result["reverse_with"] = (
        "call this tool again with the previous values; they are in snapshot %s (%s)"
        % (snapshot["snapshot_id"], snapshot["path"])
    )
    return result


# ===========================================================================
# B. Auto-reply
# ===========================================================================


def auto_reply_body(
    current: dict,
    *,
    enabled: Any = None,
    hours: Any = None,
    categories: Any = None,
) -> dict:
    """The exact 3-key body. All three are always sent.

    The one client-side gate Uplers runs is mirrored exactly: enabling with an
    empty ``auto_reply_categories`` is refused, with their own wording. Their
    check is ``!handle_auto_reply || categories.length !== 0`` - so it fires
    only on ENABLE, and disabling with an empty list is allowed.
    """
    handle = (
        bool(current.get("handle_auto_reply")) if enabled is None else bool(enabled)
    )
    if hours is None:
        live_hours = current.get("hours")
        if live_hours is None:
            raise OutreachWriteRefused(
                "The live auto-reply record carries no `hours`, and this route sends "
                "all three keys on every call - so there is no value to carry over "
                "and none may be invented. Pass hours=<whole number> explicitly. "
                "Nothing was sent."
            )
        delay = as_int(live_hours, field="hours")
    else:
        delay = as_int(hours, field="hours")

    if categories is None:
        wanted = list(current.get("auto_reply_categories") or [])
    else:
        if isinstance(categories, str) or not isinstance(categories, Iterable):
            raise OutreachWriteRefused(
                "categories must be a list of category names, not %s. Nothing was "
                "sent." % type(categories).__name__
            )
        seen: set[str] = set()
        wanted = []
        for item in categories:
            text = str(item or "").strip()
            if not text or text in seen:
                continue
            seen.add(text)
            wanted.append(text)

    if handle and not wanted:
        raise OutreachWriteRefused(
            "%s. Uplers' own editor refuses this before sending and so does this: "
            "an auto-reply switched on with nothing to answer is a setting that "
            "cannot do anything. Nothing was sent."
            % AUTO_REPLY_EMPTY_CATEGORIES_ERROR
        )

    return {
        "hours": delay,
        "handle_auto_reply": handle,
        "auto_reply_categories": wanted,
    }


async def set_auto_reply(
    client: Any,
    *,
    enabled: Any = None,
    hours: Any = None,
    categories: Any = None,
    confirm: bool = False,
    send: Any = None,
) -> dict:
    """Whether software answers his recruiter replies, and to what. Reversible.

    Same six steps as :func:`set_followup`, and the same reason for each. The
    one thing specific to this route is the unknown-category report: the eight
    names this server knows come from ONE capture of HIS account, not from
    Uplers' enum, so a name outside them is NOT rejected - it is named in the
    preview, where a typo is visible before anybody confirms.
    """
    payload = await client.get_json(EP_READ_AUTO_REPLY)
    current = read_auto_reply(payload)

    body = auto_reply_body(
        current, enabled=enabled, hours=hours, categories=categories
    )
    baseline = auto_reply_body(current)

    changes = diff_of(baseline, body)
    # Category ORDER is not a change. Uplers' payload is a list, but nothing in
    # their client reads it positionally and a re-ordered list would otherwise
    # look like a real edit forever. Set comparison here, list on the wire.
    if set(body["auto_reply_categories"]) == set(baseline["auto_reply_categories"]):
        changes = [row for row in changes if row["field"] != "auto_reply_categories"]

    if not changes:
        raise OutreachWriteRefused(
            "Nothing would change: auto-reply already holds every value you named "
            "(enabled=%r, hours=%r, %d categories). Refusing to re-send an "
            "unchanged record. Nothing was sent."
            % (
                current.get("handle_auto_reply"),
                current.get("hours"),
                len(current.get("auto_reply_categories") or []),
            )
        )

    unknown = [
        name
        for name in body["auto_reply_categories"]
        if name not in KNOWN_AUTO_REPLY_CATEGORIES
    ]

    common = {
        "action": "set_auto_reply",
        "method": _method_of(send, "POST application/json"),
        "endpoint": _endpoint_of(send),
        "body": body,
        "body_keys": sorted(body),
        "changes": changes,
        "reversible": True,
        "current": dict(current),
        "unknown_categories": unknown,
        "notes": [
            "All three keys go on every call - that is their own client's shape.",
        ],
    }
    if unknown:
        common["notes"].append(
            "NOT REJECTED, BUT CHECK IT: %s %s outside the eight categories this "
            "server has ever measured on your account (%s). The eight came from one "
            "capture, not from Uplers' enum, so an unknown name may be perfectly "
            "valid - or a typo that will be silently ignored. It is named here so "
            "you can tell which before confirming."
            % (
                ", ".join(unknown),
                "is" if len(unknown) == 1 else "are",
                ", ".join(KNOWN_AUTO_REPLY_CATEGORIES),
            )
        )
    if body["handle_auto_reply"] and "asking_resume" in body["auto_reply_categories"]:
        common["notes"].append(
            "This turns on automatic answers to `asking_resume` - somebody asking "
            "him for his resume gets a reply from software. Stated as a fact about "
            "what the setting does; the decision is his."
        )

    if not confirm:
        result = dict(common)
        result["performed"] = False
        result["snapshot"] = {"written": False}
        result["to_confirm"] = "uplers_set_auto_reply(..., confirm=True)"
        result["notes"].insert(
            0,
            "PREVIEW - nothing was sent and no snapshot was written.",
        )
        return result

    _require_sender(send)
    snapshot = write_snapshot(current, kind="auto-reply", label="pre-write")

    response = await send(body)

    verification = await _verify(
        client, route=EP_READ_AUTO_REPLY, reader=read_auto_reply, expected=dict(body)
    )

    result = dict(common)
    result["performed"] = True
    result["snapshot"] = dict(snapshot, written=True)
    result["response"] = response if isinstance(response, dict) else {}
    result["verified"] = verification
    result["reverse_with"] = (
        "uplers_set_auto_reply(enabled=%r, hours=%r, categories=%r, confirm=True)"
        % (
            current.get("handle_auto_reply"),
            current.get("hours"),
            list(current.get("auto_reply_categories") or []),
        )
    )
    return result


# ===========================================================================
# C. Message template
# ===========================================================================


def template_body(channel: Any, template: Any, subject: Any = None) -> dict:
    """The exact 3-key body for ONE channel. ``provider`` is an INTEGER.

    Path B's shape, VERIFIED at all six of its call sites: exactly
    ``{message_template, message_subject, provider}`` and **no ``tag``**. Path A
    (the preview screen) adds `tag` and is deliberately not built - see
    :data:`TEMPLATE_BODY_KEYS`.

    ``message_subject`` is sent on BOTH channels, as the empty string when
    there is none. Their editor does the same (`A.title || ""`), and it is the
    Path A LinkedIn body - not this one - that omits the key entirely.
    """
    provider = provider_for(channel)
    text = "" if template is None else str(template)
    if not text.strip():
        raise OutreachWriteRefused(
            "The template body is empty, which would blank the %s template Uplers "
            "holds. There is no delete-template route on Uplers, so this server "
            "treats blanking one as a mistake rather than a command. Nothing was "
            "sent." % str(channel)
        )
    return {
        "message_template": text,
        "message_subject": "" if subject is None else str(subject),
        "provider": provider,
    }


async def set_message_template(
    client: Any,
    channel: Any,
    template: Any,
    subject: Any = None,
    *,
    confirm: bool = False,
    send: Any = None,
) -> dict:
    """Replace ONE channel's outreach template. Reversible ONLY via the snapshot.

    **THERE IS NO DELETE-TEMPLATE ROUTE ANYWHERE IN UPLERS' BUNDLE.** The
    read-back GET returns whatever is current, so once this write lands the
    previous text is unreachable through their API. The pre-flight snapshot is
    the only way back and it is a hard precondition, not a warning.

    **The prior body is never printed.** It is written to the snapshot file and
    reported as a length and a checksum. The template YOU pass in is echoed in
    full in the exact-body preview, because that is the thing being authorised.
    """
    body = template_body(channel, template, subject)
    key = str(channel).strip().lower()

    payload = await client.get_json(EP_READ_TEMPLATES)
    current_all = read_templates(payload)
    current = current_all.get(key, {"message_template": "", "message_subject": ""})

    changes = diff_of(
        {
            "message_template": current.get("message_template") or "",
            "message_subject": current.get("message_subject") or "",
        },
        {
            "message_template": body["message_template"],
            "message_subject": body["message_subject"],
        },
    )
    if not changes:
        raise OutreachWriteRefused(
            "Nothing would change: the %s template on your account is already "
            "exactly this text with exactly this subject. Refusing to overwrite a "
            "template with itself on a route that has no undo. Nothing was sent."
            % key
        )

    common = {
        "action": "set_message_template",
        "channel": key,
        "provider": body["provider"],
        "method": _method_of(send, "POST application/json"),
        "endpoint": _endpoint_of(send),
        # The caller's own text, echoed in full. This is the ONE place personal
        # text is printed, and it is printed because it is theirs and they are
        # being asked to authorise sending exactly it.
        "body": body,
        "body_keys": sorted(body),
        "changes": changes,
        "reversible": True,
        "current": {
            # The EXISTING template, described and never quoted. Everything in
            # this repo that reads a template reports existence and subject.
            "exists": bool((current.get("message_template") or "").strip()),
            "subject": current.get("message_subject") or "",
            "body_withheld": True,
            "body_length": len(current.get("message_template") or ""),
        },
        "notes": [
            "provider is a NUMBER on this route: 1 = LinkedIn, 2 = Gmail. This call "
            "sends provider=%d for %s. Sending the string %r would be a different "
            "call to the same route." % (body["provider"], key, key),
            "ONE CHANNEL PER CALL. Writing this template does not resend the other "
            "one - their own client pushes the two POSTs independently, each behind "
            "its own changed-and-connected guard.",
            "THERE IS NO DELETE-TEMPLATE ROUTE ON UPLERS. The snapshot taken before "
            "this write is the only copy of the previous text that will exist.",
            "The template currently on your account is NOT printed here, on purpose "
            "- it is a multi-paragraph self-description and a tool result ends up in "
            "a transcript. Its length and subject are above; its full text goes into "
            "the snapshot file.",
        ],
    }

    if not confirm:
        result = dict(common)
        result["performed"] = False
        result["snapshot"] = {"written": False}
        result["to_confirm"] = (
            "uplers_set_message_template(%r, <the same template>, confirm=True)" % key
        )
        result["notes"].insert(
            0,
            "PREVIEW - nothing was sent and no snapshot was written. Confirming "
            "writes the current %s template to disk first (that is the only undo "
            "there is), then sends." % key,
        )
        return result

    _require_sender(send)
    # The WHOLE templates record, both channels, not just the one being
    # overwritten: the file costs nothing extra and a snapshot that holds half
    # the record is a restore point that has to be reasoned about.
    snapshot = write_snapshot(current_all, kind="template", label="pre-write")

    response = await send(body)

    verification = await _verify(
        client,
        route=EP_READ_TEMPLATES,
        reader=lambda raw: read_templates(raw).get(key, {}),
        expected={
            "message_template": body["message_template"],
            "message_subject": body["message_subject"],
        },
    )

    result = dict(common)
    result["performed"] = True
    result["snapshot"] = dict(snapshot, written=True)
    result["response"] = response if isinstance(response, dict) else {}
    result["verified"] = verification
    result["reverse_with"] = (
        "the previous %s template is in snapshot %s (%s) - load it with "
        "outreach_write.load_snapshot(%r) and pass its text back into this tool. "
        "Uplers has no delete-template route, so that file is the only way back."
        % (key, snapshot["snapshot_id"], snapshot["path"], snapshot["snapshot_id"])
    )
    return result


# ===========================================================================
# D. Blocked companies - the one genuinely PAIRED write
# ===========================================================================


def find_blocked(rows: Iterable[dict], company_id: Any) -> dict | None:
    """The blocklist row for a company, or None. Matches on ``company_id``.

    Matching on the row's own ``id`` here would be the identifier-space bug
    this module exists to avoid: both fields are small integers, both are
    present on every row, and the caller names a COMPANY.
    """
    for row in rows:
        if row.get("company_id") is not None and str(row["company_id"]) == str(
            company_id
        ):
            return row
    return None


def _company_id(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        try:
            value = int(str(value).strip())
        except (TypeError, ValueError):
            raise OutreachWriteRefused(
                "%r is not a company id. Uplers' blocklist rows carry a numeric "
                "`company_id`; read them with the agent-settings tool. Nothing was "
                "sent." % (value,)
            ) from None
    if value <= 0:
        raise OutreachWriteRefused(
            "%d is not a company id. Nothing was sent." % value
        )
    return value


async def block_company(
    client: Any,
    company_id: Any,
    *,
    confirm: bool = False,
    send: Any = None,
) -> dict:
    """Add a company to the outreach blocklist. Genuinely reversible.

    The one PAIRED write in this module: Uplers' own two toasts name the pair -
    "Company added to disabled list" / "Company removed from disabled list" -
    so the way back is a route rather than a saved value.

    The live list is read first anyway, because "block a company that is
    already blocked" is guard 4's case and the only way to know is to look.
    """
    identifier = _company_id(company_id)

    payload = await client.get_json(EP_READ_DISABLED_COMPANIES)
    rows = read_blocklist(payload)
    existing = find_blocked(rows, identifier)

    if existing is not None:
        raise OutreachWriteRefused(
            "Company %d (%s) is already on the outreach blocklist as row %s, so "
            "this would change nothing. Nothing was sent."
            % (identifier, existing.get("company_name") or "unnamed", existing.get("id"))
        )

    body = {"company_id": identifier}
    common = {
        "action": "block_company",
        "company_id": identifier,
        "method": _method_of(send, "POST application/json"),
        "endpoint": _endpoint_of(send),
        "body": body,
        "body_keys": sorted(body),
        "reversible": True,
        "current": {"blocked_companies": len(rows), "already_blocked": False},
        "notes": [
            "A blocked company is skipped SILENTLY by the agent - the run fails with "
            '"You blocked this company for outreach" and nothing else says why.',
            "This list is talent/outreach/settings/disabled-companies. It is NOT "
            "settings/companies, which is an alphabetical picker paginated at 20 "
            "rows; reading a blocklist off that one would report the first twenty "
            "companies in the alphabet as blocked.",
            "This is the reversible pair: the same company can be unblocked with "
            "the DELETE arm, which takes the blocklist ROW id, not this company id.",
        ],
    }

    if not confirm:
        result = dict(common)
        result["performed"] = False
        result["snapshot"] = {"written": False}
        result["to_confirm"] = "uplers_block_company(%d, confirm=True)" % identifier
        result["notes"].insert(0, "PREVIEW - nothing was sent.")
        return result

    _require_sender(send)
    snapshot = write_snapshot(rows, kind="blocklist", label="pre-block")

    response = await send(body)

    verification: dict
    try:
        after = read_blocklist(await client.get_json(EP_READ_DISABLED_COMPANIES))
    except UplersError as exc:
        verification = {
            "re_read": False,
            "landed": None,
            "route": EP_READ_DISABLED_COMPANIES,
            "error": "%s: %s" % (type(exc).__name__, exc),
        }
    else:
        row = find_blocked(after, identifier)
        verification = {
            "re_read": True,
            "landed": row is not None,
            "route": EP_READ_DISABLED_COMPANIES,
            "blocklist_row_id": row.get("id") if row else None,
            "blocked_companies": len(after),
            "note": (
                "Verified by reading the list back. The row id above is what an "
                "unblock takes as its path segment - it is NOT the company id."
            )
            if row is not None
            else (
                "THE WRITE DID NOT LAND: the route accepted the request and the "
                "company is still not on the blocklist."
            ),
        }

    result = dict(common)
    result["performed"] = True
    result["snapshot"] = dict(snapshot, written=True)
    result["response"] = response if isinstance(response, dict) else {}
    result["verified"] = verification
    result["reverse_with"] = "uplers_unblock_company(%d, confirm=True)" % identifier
    return result


async def unblock_company(
    client: Any,
    company_id: Any,
    *,
    confirm: bool = False,
    send: Any = None,
) -> dict:
    """Remove a company from the outreach blocklist. The DELETE half of the pair.

    **The path segment is the blocklist ROW id, and it is resolved HERE from the
    live list rather than taken from the caller.** The caller names a COMPANY;
    the row id is Uplers' internal handle for "this company on this blocklist",
    it changes if the company is unblocked and re-blocked, and both numbers sit
    on the same row. A caller who passed one thinking it was the other would
    unblock a different company - or nothing - and get a 200 either way. Reading
    the list first is guard 1 doing the work it exists for.
    """
    identifier = _company_id(company_id)

    payload = await client.get_json(EP_READ_DISABLED_COMPANIES)
    rows = read_blocklist(payload)
    existing = find_blocked(rows, identifier)

    if existing is None:
        raise OutreachWriteRefused(
            "Company %d is not on the outreach blocklist (%d companies are), so "
            "there is nothing to remove and this would change nothing. Nothing was "
            "sent." % (identifier, len(rows))
        )
    row_id = existing.get("id")
    if row_id is None:
        raise OutreachWriteRefused(
            "Company %d is on the blocklist but its row carries no `id`, which is "
            "the path segment the unblock needs. Refusing to guess one - the only "
            "other number on the row is the company id, and sending that would "
            "delete somebody else's row. Nothing was sent." % identifier
        )

    common = {
        "action": "unblock_company",
        "company_id": identifier,
        "company_name": existing.get("company_name"),
        "blocklist_row_id": row_id,
        "method": _method_of(send, "DELETE"),
        "endpoint": _endpoint_of(send),
        # A DELETE with no body. `body` is empty and `path_id` carries the one
        # value that decides what happens, so the preview still shows the whole
        # decision - which is what guard 2 is for, body or no body.
        "body": {},
        "path_id": row_id,
        "reversible": True,
        "current": {"blocked_companies": len(rows), "already_blocked": True},
        "notes": [
            "This DELETE takes its id as a PATH SEGMENT and sends no body.",
            "The id sent is the blocklist ROW id (%s), resolved from the live list, "
            "NOT the company id (%d). Both live on the same row and both are small "
            "integers; sending the wrong one removes a different company, with a 200 "
            "either way." % (row_id, identifier),
            "This is the reversible pair: uplers_block_company puts it back.",
        ],
    }

    if not confirm:
        result = dict(common)
        result["performed"] = False
        result["snapshot"] = {"written": False}
        result["to_confirm"] = "uplers_unblock_company(%d, confirm=True)" % identifier
        result["notes"].insert(0, "PREVIEW - nothing was sent.")
        return result

    _require_sender(send)
    snapshot = write_snapshot(rows, kind="blocklist", label="pre-unblock")

    response = await send(row_id)

    verification: dict
    try:
        after = read_blocklist(await client.get_json(EP_READ_DISABLED_COMPANIES))
    except UplersError as exc:
        verification = {
            "re_read": False,
            "landed": None,
            "route": EP_READ_DISABLED_COMPANIES,
            "error": "%s: %s" % (type(exc).__name__, exc),
        }
    else:
        still_there = find_blocked(after, identifier) is not None
        verification = {
            "re_read": True,
            "landed": not still_there,
            "route": EP_READ_DISABLED_COMPANIES,
            "blocked_companies": len(after),
            "note": (
                "Verified by reading the list back - the DELETE's own response is "
                "only a status."
            )
            if not still_there
            else (
                "THE WRITE DID NOT LAND: the route accepted the request and the "
                "company is still on the blocklist."
            ),
        }

    result = dict(common)
    result["performed"] = True
    result["snapshot"] = dict(snapshot, written=True)
    result["response"] = response if isinstance(response, dict) else {}
    result["verified"] = verification
    result["reverse_with"] = "uplers_block_company(%d, confirm=True)" % identifier
    return result
