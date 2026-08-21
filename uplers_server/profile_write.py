"""Snapshot, plan, and restore for the one write that can change WHO HE IS.

Every other write in this server acts on a requisition - apply, dismiss, save.
This one acts on him, and it is the only place in the codebase where a bug
deletes something that took a person an afternoon to type in.

**The route is REPLACEMENT semantics.** VERIFIED against Uplers' own bundle,
with five independent links and the verbatim call sites recorded in
`_audit/2026-08-21-uplers-skills-write-shape.md`:

    POST talent/profile-upsert  {"field": "skills", "value": [<EVERY skill>]}

The decisive one is their remove handler. Deleting a skill chip in Uplers' UI
fires **no network call at all** - `n.splice(t,1)` and nothing else. A removal
reaches the server purely as an omission from the next full-array POST. Two
consequences that shape every function here:

1.  **A write must send the COMPLETE desired list**, each row carrying `id`,
    `label`, `years_of_experience` and `order`. A request that looks like a
    sensible "add Rust" - `value: [{"label": "Rust"}]` - deletes sixty skills
    and loses the recorded years on the rest. So rows are rebuilt from the live
    profile, never from names.

2.  **An empty array is the most destructive thing this endpoint accepts**, and
    it is refused here before it can be built. Uplers' own UI refuses it too
    ("Please add your skills"), which is corroboration rather than a reason -
    a client-side guard is not a server-side one.

The restore guards are inherited from the sibling Instahyre server, where the
version WITHOUT them destroyed real data: a `snapshot_id` of
`"../not-a-snapshot"` escaped the snapshots directory, resolved to a file with
no skills in it, and the "restore" deleted all four of his. Three checks, each
of which independently stops that: the id must look like an id, the resolved
path must stay inside the directory, and the record must actually contain
skills. Against a replacement route the third is the one that matters most -
restoring an empty snapshot is not a no-op, it is an instruction to delete
everything.

**Nothing here performs a request.** This module plans and persists; the two
write tools in `server.py` are the only callers that send anything, which is
what keeps the write un-invokable as a side effect.
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any, Iterable

from . import config, talent_shape
from .client import UplersError

#: What :func:`write_snapshot` names its files: a unix timestamp, a hyphen, and
#: a lowercase label. Anything else is not an id this server wrote, and a
#: restore is far too destructive to run against a file of unknown origin.
SNAPSHOT_ID_RE = re.compile(r"[0-9]{1,20}-[a-z0-9-]{1,40}")

#: The four fields Uplers' own editor puts on every row. An omitted one is not
#: "unchanged" - on a replacement route it is erased.
REQUIRED_ROW_FIELDS = ("id", "label", "years_of_experience", "order")


class WriteRefused(UplersError):
    """A write was stopped before anything left the machine.

    Distinct from a failure: nothing was attempted, nothing changed, and the
    message says which guard fired.
    """

    kind = "write_refused"


def snapshots_dir() -> Path:
    path = config.DATA_DIR / "profile_snapshots"
    path.mkdir(parents=True, exist_ok=True)
    return path


# --- reading the current set ----------------------------------------------


def current_skill_rows(payload: Any) -> list[dict]:
    """The live skill list as the rows Uplers wants back, in its own order.

    Built by joining `talent_details.skills` against `masters.skills`, because
    the profile rows carry only `skill_id` - see `talent_shape.MASTERS_KEY`.
    Rebuilding from names instead would flatten `years_of_experience` to zero
    on every row, which on a replacement route means deleting that data.
    """
    if not isinstance(payload, dict):
        raise WriteRefused(
            "The profile read returned %s, not an object, so the current skill list "
            "is unknown. Refusing to build a replacement write without it."
            % type(payload).__name__
        )
    details = payload.get(talent_shape.PROFILE_KEY)
    if not isinstance(details, dict):
        raise WriteRefused(
            "The profile read carried no `%s`, so the current skill list is unknown. "
            "A replacement write built on a failed read would delete everything it "
            "could not see." % talent_shape.PROFILE_KEY
        )

    lookup = (talent_shape.masters_index(payload) or {}).get("skills") or {}
    rows: list[dict] = []
    seen: set[str] = set()
    # `skills` is the superset; `primaryskills` is a filtered view of the same
    # underlying rows, and the response repopulates it from this one field.
    for raw in details.get("skills") or []:
        if not isinstance(raw, dict):
            continue
        identifier = raw.get("skill_id")
        label = lookup.get(str(identifier))
        if not label:
            raise WriteRefused(
                "Skill id %r has no name in Uplers' own lookup, so a replacement write "
                "cannot round-trip it. Sending the list anyway would silently drop it. "
                "Re-read the profile and try again." % identifier
            )
        key = label.strip().lower()
        if key in seen:
            continue
        seen.add(key)
        rows.append(
            {
                "id": identifier,
                "label": label,
                "years_of_experience": raw.get("years_of_experience", 0),
                "order": raw.get("order", 0),
            }
        )
    return rows


def master_id_for(payload: Any, name: str) -> int | str:
    """The master id for a skill name, or `""` for one Uplers does not know.

    VERIFIED in their bundle: `id` is the numeric master id, or the empty
    string for a free-typed skill. Inventing an integer would point the row at
    somebody else's skill.
    """
    lookup = (talent_shape.masters_index(payload) or {}).get("skills") or {}
    wanted = str(name).strip().lower()
    for identifier, label in lookup.items():
        if str(label).strip().lower() == wanted:
            return int(identifier) if str(identifier).isdigit() else identifier
    return ""


def canonical_label(payload: Any, name: str) -> str:
    """Uplers' own spelling for a skill, so a write does not create a variant."""
    lookup = (talent_shape.masters_index(payload) or {}).get("skills") or {}
    wanted = str(name).strip().lower()
    for label in lookup.values():
        if str(label).strip().lower() == wanted:
            return str(label)
    return str(name).strip()


# --- planning the write ----------------------------------------------------


def plan_skills(
    payload: Any,
    *,
    add: Iterable[str] = (),
    remove: Iterable[str] = (),
) -> dict:
    """`{value, added, removed, unchanged}` - the COMPLETE array to send.

    Refuses rather than returns on the two cases where sending would destroy
    something: an empty result, and a change that changes nothing.
    """
    rows = current_skill_rows(payload)
    existing = {row["label"].strip().lower(): row for row in rows}

    drop = {str(name).strip().lower() for name in remove if str(name).strip()}
    unknown_removals = sorted(name for name in drop if name not in existing)

    kept = [row for row in rows if row["label"].strip().lower() not in drop]
    removed = sorted(
        row["label"] for row in rows if row["label"].strip().lower() in drop
    )

    added: list[str] = []
    for name in add:
        text = str(name).strip()
        if not text:
            continue
        key = text.lower()
        if key in {row["label"].strip().lower() for row in kept}:
            continue
        label = canonical_label(payload, text)
        kept.append(
            {
                "id": master_id_for(payload, text),
                "label": label,
                # A skill he has just named has no recorded depth yet. Uplers
                # writes 0 for "not recorded", so that is what is sent.
                "years_of_experience": 0,
                "order": 0,
            }
        )
        added.append(label)

    if not kept:
        raise WriteRefused(
            "That would send an EMPTY skill list. This route replaces the whole set, "
            "so an empty array deletes every skill on your profile - it is the single "
            "most destructive request this endpoint accepts, and Uplers' own editor "
            "refuses it too. Nothing was sent."
        )
    if not added and not removed:
        raise WriteRefused(
            "Nothing would change: %s. Refusing to re-send %d unchanged rows to a "
            "replacement endpoint for no benefit."
            % (
                "those skills are already on the profile"
                if not unknown_removals
                else "no skill named %s is on the profile" % ", ".join(unknown_removals),
                len(kept),
            )
        )

    return {
        "value": kept,
        "added": added,
        "removed": removed,
        "unchanged": len(kept) - len(added),
        "unknown_removals": unknown_removals,
    }


def request_body(value: list[dict]) -> dict:
    """The exact body Uplers' editor sends. Shape VERIFIED in their bundle."""
    for row in value:
        missing = [field for field in REQUIRED_ROW_FIELDS if field not in row]
        if missing:
            raise WriteRefused(
                "A skill row is missing %s. On a replacement route an omitted field is "
                "erased, not left alone, so the write is refused." % ", ".join(missing)
            )
    return {"field": "skills", "value": value}


# --- snapshots -------------------------------------------------------------


def write_snapshot(payload: Any, *, label: str = "auto") -> dict:
    """Persist a restore point. ALWAYS runs before a write, never after.

    Ordering is the property, not existence: a snapshot taken after a write
    that half-succeeded records the damage rather than the way back.

    Holds the skill rows and nothing else. His pay, contact details and
    identity documents arrive in the same payload and none of them is written
    here - a snapshot is a rollback tool, and personal data sitting in a file
    on disk is a liability that buys nothing.
    """
    rows = current_skill_rows(payload)
    clean_label = re.sub(r"[^a-z0-9-]+", "-", str(label).lower()).strip("-") or "auto"
    record = {
        "snapshot_id": "%d-%s" % (int(time.time()), clean_label[:40]),
        "taken_at": time.time(),
        "label": clean_label[:40],
        "skills": rows,
    }
    path = snapshots_dir() / ("%s.json" % record["snapshot_id"])
    path.write_text(json.dumps(record, indent=2, ensure_ascii=False), encoding="utf-8")
    return {
        "snapshot_id": record["snapshot_id"],
        "path": str(path),
        "skills": len(rows),
    }


def list_snapshots() -> list[dict]:
    """Newest first. A snapshot that cannot be parsed is skipped, not raised on -
    listing is a read and must survive one corrupt file."""
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
                "taken_at": data.get("taken_at"),
                "label": data.get("label"),
                "skills": len(data.get("skills") or []),
            }
        )
    return out


def load_snapshot(snapshot_id: str | None = None) -> dict:
    """A restore point, refusing anything that is not obviously one.

    `snapshot_id` arrives raw from an agent-callable tool, so it is untrusted
    input naming a file. All three checks below exist because the version
    without them did real damage in the sibling server - see the module
    docstring. None is redundant: the pattern check can be loosened by a future
    edit, so the containment check stands behind it, and both are about WHICH
    file is read while the third is about what restoring it would DO.
    """
    # Validate the id FIRST, before looking at what is on disk. Ordering these
    # the other way round made the traversal guard conditional on the directory
    # being non-empty: `../not-a-snapshot` against an empty directory got the
    # friendly "no snapshots yet" message instead of a refusal. Same outcome
    # that time, but a safety check that only runs in some directory states is
    # not a safety check.
    if snapshot_id is not None and not SNAPSHOT_ID_RE.fullmatch(str(snapshot_id)):
        raise WriteRefused(
            "%r is not a snapshot id. Ids look like '1755780000-pre-skills-write'. "
            "Call uplers_list_profile_snapshots() to see the real ones."
            % str(snapshot_id)[:60]
        )

    available = sorted(snapshots_dir().glob("*.json"), reverse=True)
    if not available:
        raise WriteRefused(
            "There is no snapshot to restore from. One is written automatically before "
            "every write, so an empty set means this server has never written to your "
            "Uplers profile."
        )

    if snapshot_id is None:
        path = available[0]
    else:
        directory = snapshots_dir().resolve()
        path = (directory / ("%s.json" % snapshot_id)).resolve()
        # Behind the pattern check rather than instead of it: if the pattern is
        # ever loosened, a path that escaped the directory still dies here.
        if path.parent != directory:
            raise WriteRefused(
                "Refusing to read a snapshot from outside the snapshots directory."
            )
        if not path.is_file():
            raise WriteRefused(
                "No snapshot %r. Call uplers_list_profile_snapshots()." % snapshot_id
            )

    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise WriteRefused(
            "Snapshot %s could not be read as JSON (%s). Refusing to restore from a "
            "file this server cannot understand - a restore REPLACES the whole skill "
            "list with what the snapshot holds." % (path.name, exc)
        ) from exc

    if not isinstance(record, dict) or not record.get("skills"):
        raise WriteRefused(
            "Snapshot %s holds no skills. Restoring it would not put anything back - "
            "it would delete every skill on the profile, because this route replaces "
            "the whole set. Refusing." % path.name
        )
    return record
