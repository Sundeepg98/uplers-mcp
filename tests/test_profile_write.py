"""The one tool in this server that can change who he is on Uplers.

The capability exists deliberately. The DECISION to invoke it belongs to the
calling client, which knows things this server does not - so the job here is
not to withhold the write, it is to make it impossible to fire by accident and
impossible to fire blind.

**The write is REPLACEMENT semantics, and that is the whole danger.** Uplers'
own editor sends `POST talent/profile-upsert {field:"skills", value:[<ALL
skills>]}`, and deleting a skill chip in their UI fires no network call at all
- it only shortens the local array. A removal reaches the server purely as an
omission from the next full-array POST. So a write that looks like "add React"
and forgets to carry the other 60 skills DELETES SIXTY SKILLS. Evidence, with
verbatim call sites and the five links that prove it:
`_audit/2026-08-21-uplers-skills-write-shape.md`.

Everything below is a guard against that, or against the restore path being
turned into a delete. The restore guards are copied from the sibling Instahyre
server, where the version without them destroyed real profile data in a probe:
a `snapshot_id` of `"../not-a-snapshot"` escaped the snapshots directory, read
a file with no skills in it, and a "restore" deleted all four of his.
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from test_talent_tools import make_transport, serve, wire_talent, writes
from uplers_server import endpoints, profile_write
from uplers_server.talent import TalentError

import server

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "talent_profile.json"
UPSERT_PATH = "/api/" + endpoints.EP_PROFILE_UPSERT
PROFILE_PATH = "/api/" + endpoints.EP_PROFILE


@pytest.fixture
def real_payload() -> dict:
    with FIXTURE.open(encoding="utf-8") as handle:
        return json.load(handle)


@pytest.fixture(autouse=True)
def isolated_snapshots(monkeypatch, tmp_path):
    """Snapshots go to tmp_path. Autouse: a test must not be able to write a
    restore point into the operator's real data directory by forgetting."""
    directory = tmp_path / "profile_snapshots"
    directory.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(profile_write, "snapshots_dir", lambda: directory)
    return directory


def profile_then_upsert(payload, upsert_response=None):
    """GET profile answers with `payload`; the upsert answers success."""

    def handler(request):
        if request.url.path.endswith(endpoints.EP_PROFILE_UPSERT):
            return httpx.Response(200, json=upsert_response or {"data": []})
        return httpx.Response(200, json=payload)

    return handler


def upsert_calls(calls):
    return [call for call in calls if call.url.path == UPSERT_PATH]


def sent_body(call) -> dict:
    return json.loads(call.content)


# --- the preview -----------------------------------------------------------


async def test_without_confirm_it_sends_nothing_at_all(monkeypatch, real_payload):
    calls = wire_talent(monkeypatch, profile_then_upsert(real_payload))

    result = await server.uplers_update_profile(add_skills=["Rust"])

    assert result.applied is False
    assert writes(calls) == []
    assert upsert_calls(calls) == []


async def test_the_preview_shows_the_exact_request_it_would_send(
    monkeypatch, real_payload
):
    """"Preview" that does not show the bytes is not a preview.

    The caller is being asked to authorise a replacement write. It cannot make
    that call on a summary - it needs the actual array, because the array IS
    the decision.
    """
    calls = wire_talent(monkeypatch, profile_then_upsert(real_payload))

    result = await server.uplers_update_profile(add_skills=["Rust"])

    assert result.request_method == "POST"
    assert result.request_path == endpoints.EP_PROFILE_UPSERT
    assert result.request_body["field"] == "skills"
    values = result.request_body["value"]
    assert len(values) == 62          # the 61 he has, plus Rust
    assert {"id", "label", "years_of_experience", "order"} <= set(values[0])
    assert "Rust" in [row["label"] for row in values]
    assert upsert_calls(calls) == []


async def test_the_preview_states_the_replacement_semantics(monkeypatch, real_payload):
    """A caller who thinks this is a merge will eventually send a short array."""
    wire_talent(monkeypatch, profile_then_upsert(real_payload))

    result = await server.uplers_update_profile(add_skills=["Rust"])

    warning = " ".join(result.notes).lower()
    assert "replace" in warning
    assert "omitted" in warning or "not in this list" in warning


# --- the write itself ------------------------------------------------------


async def test_confirm_sends_the_complete_list_not_just_the_addition(
    monkeypatch, real_payload
):
    """THE bug this whole file exists to prevent.

    Sending `[{"label": "Rust"}]` would read as a perfectly sensible "add
    Rust" and would delete the other 61 skills.
    """
    calls = wire_talent(monkeypatch, profile_then_upsert(real_payload))

    result = await server.uplers_update_profile(add_skills=["Rust"], confirm=True)

    posted = upsert_calls(calls)
    assert len(posted) == 1
    body = sent_body(posted[0])
    assert body["field"] == "skills"
    assert len(body["value"]) == 62
    labels = [row["label"] for row in body["value"]]
    assert "Rust" in labels
    assert "Node.js" in labels and "Kubernetes" in labels
    assert result.applied is True


async def test_every_row_carries_the_four_fields_uplers_expects(
    monkeypatch, real_payload
):
    """A row missing `years_of_experience` or `order` loses that data.

    Uplers replaces the whole set from what is sent, so an omitted field is
    not "unchanged" - it is erased.
    """
    calls = wire_talent(monkeypatch, profile_then_upsert(real_payload))

    await server.uplers_update_profile(add_skills=["Rust"], confirm=True)

    for row in sent_body(upsert_calls(calls)[0])["value"]:
        assert set(row) >= {"id", "label", "years_of_experience", "order"}
        assert isinstance(row["label"], str) and row["label"]


async def test_an_existing_skills_recorded_years_survive_the_round_trip(
    monkeypatch, real_payload
):
    """He has years recorded against three skills. A write must not flatten
    them to zero, which is what rebuilding rows from names alone would do."""
    calls = wire_talent(monkeypatch, profile_then_upsert(real_payload))

    await server.uplers_update_profile(add_skills=["Rust"], confirm=True)

    by_label = {row["label"]: row for row in sent_body(upsert_calls(calls)[0])["value"]}
    assert str(by_label["Node.js"]["years_of_experience"]) == "4"
    assert str(by_label["AWS"]["years_of_experience"]) == "3"


async def test_a_new_skill_is_sent_with_an_empty_id(monkeypatch, real_payload):
    """VERIFIED in their bundle: `id` is the master id, or "" for a free-typed
    one. Sending a made-up integer would point at somebody else's skill."""
    calls = wire_talent(monkeypatch, profile_then_upsert(real_payload))

    await server.uplers_update_profile(add_skills=["Rust"], confirm=True)

    rows = {row["label"]: row for row in sent_body(upsert_calls(calls)[0])["value"]}
    assert rows["Rust"]["id"] == ""
    assert rows["Node.js"]["id"] != ""


async def test_a_skill_uplers_already_knows_is_sent_with_its_master_id(
    monkeypatch, real_payload
):
    """"WooCommerce" is in Uplers' master list but NOT on his profile.

    Adding it must reuse the real master id (2) rather than minting a blank
    one, or Uplers stores a duplicate free-text skill alongside its own.
    """
    calls = wire_talent(monkeypatch, profile_then_upsert(real_payload))

    await server.uplers_update_profile(add_skills=["woocommerce"], confirm=True)

    rows = {row["label"]: row for row in sent_body(upsert_calls(calls)[0])["value"]}
    assert rows["WooCommerce"]["id"] == 2
    # Uplers' own spelling wins, not the caller's lowercase.
    assert "woocommerce" not in rows


async def test_adding_a_skill_he_already_has_is_not_a_second_row(
    monkeypatch, real_payload
):
    """Case must not create a duplicate. He has "Kubernetes"; adding
    "kubernetes" is the same skill, and a replacement write that sent both
    would leave him with two."""
    calls = wire_talent(monkeypatch, profile_then_upsert(real_payload))

    await server.uplers_update_profile(
        add_skills=["kubernetes", "WooCommerce"], confirm=True
    )

    labels = [row["label"] for row in sent_body(upsert_calls(calls)[0])["value"]]
    assert len([name for name in labels if name.lower() == "kubernetes"]) == 1
    assert len(labels) == 62


async def test_removal_is_expressed_as_omission_from_the_full_array(
    monkeypatch, real_payload
):
    """There is no delete route for skills - VERIFIED, and it is why removal
    has to work this way. Every sibling section has `delete-details`; skills
    does not."""
    calls = wire_talent(monkeypatch, profile_then_upsert(real_payload))

    result = await server.uplers_update_profile(remove_skills=["Python"], confirm=True)

    body = sent_body(upsert_calls(calls)[0])
    labels = [row["label"] for row in body["value"]]
    assert "Python" not in labels
    assert len(labels) == 60
    assert result.skills_removed == ["Python"]


async def test_a_write_that_would_change_nothing_is_refused(monkeypatch, real_payload):
    """A no-op write is all risk and no benefit: it spends his rate budget and
    re-sends 61 rows for nothing."""
    calls = wire_talent(monkeypatch, profile_then_upsert(real_payload))

    with pytest.raises(Exception) as excinfo:
        await server.uplers_update_profile(add_skills=["Node.js"], confirm=True)

    assert "already" in str(excinfo.value).lower()
    assert upsert_calls(calls) == []


async def test_an_empty_resulting_list_is_refused_before_any_request(
    monkeypatch, real_payload
):
    """Their own UI refuses this ("Please add your skills"), and an empty array
    against a replacement route is the single most destructive thing that could
    be sent to this endpoint."""
    every_skill = [
        row["label"]
        for row in json.loads(FIXTURE.read_text(encoding="utf-8"))["masters"]["skills"]
    ]
    calls = wire_talent(monkeypatch, profile_then_upsert(real_payload))

    with pytest.raises(Exception) as excinfo:
        await server.uplers_update_profile(remove_skills=every_skill, confirm=True)

    assert "empty" in str(excinfo.value).lower()
    assert upsert_calls(calls) == []


# --- the snapshot ----------------------------------------------------------


async def test_a_snapshot_is_written_before_the_request_goes_out(
    monkeypatch, real_payload, isolated_snapshots
):
    """Ordering is the property, not existence. A snapshot taken after a write
    that half-succeeded records the damage, not the way back."""
    order = []

    def handler(request):
        if request.url.path.endswith(endpoints.EP_PROFILE_UPSERT):
            order.append("write")
            order.append("snapshots=%d" % len(list(isolated_snapshots.glob("*.json"))))
            return httpx.Response(200, json={"data": []})
        return httpx.Response(200, json=real_payload)

    wire_talent(monkeypatch, handler)

    result = await server.uplers_update_profile(add_skills=["Rust"], confirm=True)

    assert order[0] == "write"
    assert order[1] == "snapshots=1", "the snapshot must exist BEFORE the write fires"
    assert result.snapshot_id


async def test_the_preview_takes_no_snapshot(monkeypatch, real_payload, isolated_snapshots):
    wire_talent(monkeypatch, profile_then_upsert(real_payload))

    await server.uplers_update_profile(add_skills=["Rust"])

    assert list(isolated_snapshots.glob("*.json")) == []


async def test_the_snapshot_holds_the_rows_needed_to_put_them_back(
    monkeypatch, real_payload, isolated_snapshots
):
    wire_talent(monkeypatch, profile_then_upsert(real_payload))

    await server.uplers_update_profile(add_skills=["Rust"], confirm=True)

    record = json.loads(next(isolated_snapshots.glob("*.json")).read_text(encoding="utf-8"))
    assert len(record["skills"]) == 61
    assert {"id", "label", "years_of_experience", "order"} <= set(record["skills"][0])


def test_a_snapshot_never_holds_anything_private(real_payload, isolated_snapshots):
    """A snapshot is a rollback tool. His pay and contact details on disk buy
    nothing and are a liability."""
    profile_write.write_snapshot(real_payload, label="test")

    blob = next(isolated_snapshots.glob("*.json")).read_text(encoding="utf-8")
    for name in (
        "current_ctc",
        "expected_ctc",
        "monthly_salary",
        "dob",
        "contact_number",
        "whatsapp_optin",
        "address",
        "email",
        "profile_pic_url",
        "resume_url",
    ):
        assert name not in blob


# --- restore ---------------------------------------------------------------


async def test_restore_without_confirm_changes_nothing(
    monkeypatch, real_payload, isolated_snapshots
):
    profile_write.write_snapshot(real_payload, label="seed")
    calls = wire_talent(monkeypatch, profile_then_upsert(real_payload))

    result = await server.uplers_restore_profile()

    assert result.applied is False
    assert upsert_calls(calls) == []


async def test_restore_sends_the_snapshotted_array(
    monkeypatch, real_payload, isolated_snapshots
):
    record = profile_write.write_snapshot(real_payload, label="seed")
    calls = wire_talent(monkeypatch, profile_then_upsert(real_payload))

    result = await server.uplers_restore_profile(
        snapshot_id=record["snapshot_id"], confirm=True
    )

    body = sent_body(upsert_calls(calls)[0])
    assert body["field"] == "skills"
    assert len(body["value"]) == 61
    assert result.applied is True


async def test_a_traversing_snapshot_id_is_refused(monkeypatch, isolated_snapshots, tmp_path):
    """The exact probe that destroyed data in the sibling server.

    `../not-a-snapshot` resolved outside the snapshots directory, was read as a
    file with no skills in it, and the restore deleted every skill. The file is
    planted here so the test fails for the RIGHT reason - a refusal, not a
    missing file.
    """
    (tmp_path / "not-a-snapshot.json").write_text('{"skills": []}', encoding="utf-8")
    calls = wire_talent(monkeypatch, serve({}))

    with pytest.raises(Exception) as excinfo:
        await server.uplers_restore_profile(
            snapshot_id="../not-a-snapshot", confirm=True
        )

    assert "not a snapshot id" in str(excinfo.value).lower()
    assert upsert_calls(calls) == []


@pytest.mark.parametrize(
    "bad_id",
    ["../not-a-snapshot", "..\\..\\windows\\system32", "/etc/passwd", "a" * 200, "", "."],
)
async def test_no_shape_of_hostile_snapshot_id_reaches_the_filesystem(
    monkeypatch, isolated_snapshots, bad_id
):
    calls = wire_talent(monkeypatch, serve({}))

    with pytest.raises(Exception):
        await server.uplers_restore_profile(snapshot_id=bad_id, confirm=True)

    assert upsert_calls(calls) == []


async def test_a_snapshot_holding_no_skills_is_refused_as_a_delete_instruction(
    monkeypatch, isolated_snapshots
):
    """This is the guard that actually mattered in the sibling incident.

    Against a replacement-semantics route, restoring an empty snapshot is not a
    harmless no-op - it is an instruction to delete every skill.
    """
    path = isolated_snapshots / "1755780000-empty.json"
    path.write_text(json.dumps({"snapshot_id": "1755780000-empty", "skills": []}), encoding="utf-8")
    calls = wire_talent(monkeypatch, serve({}))

    with pytest.raises(Exception) as excinfo:
        await server.uplers_restore_profile(snapshot_id="1755780000-empty", confirm=True)

    message = str(excinfo.value).lower()
    assert "no skills" in message or "delete every" in message
    assert upsert_calls(calls) == []


async def test_listing_snapshots_needs_no_session_and_writes_nothing(
    real_payload, isolated_snapshots
):
    profile_write.write_snapshot(real_payload, label="one")
    profile_write.write_snapshot(real_payload, label="two")

    result = await server.uplers_list_profile_snapshots()

    assert len(result.snapshots) == 2
    assert all(entry.snapshot_id for entry in result.snapshots)
    assert all(entry.skills == 61 for entry in result.snapshots)


# --- the standing guarantee, restated for the new design -------------------


def test_the_upsert_route_is_reachable_from_the_write_tools_and_nowhere_else():
    """The capability exists; what must never happen is it firing by itself.

    Not "no write exists" - that was the old design and it was wrong. The
    guarantee now is that no read, no sync, no scheduled task and no
    reconciliation can reach the write. It is invoked because a caller decided
    to invoke it, or not at all.
    """
    root = Path(__file__).resolve().parent.parent
    sources = [root / "server.py"] + sorted((root / "uplers_server").glob("*.py"))

    callers = []
    for source in sources:
        if source.name in ("endpoints.py", "profile_write.py"):
            continue
        for number, line in enumerate(source.read_text(encoding="utf-8").splitlines(), 1):
            if "EP_PROFILE_UPSERT" in line and not line.strip().startswith("#"):
                callers.append("%s:%d" % (source.name, number))

    assert callers, "the constant vanished - this test is no longer testing anything"
    for caller in callers:
        assert caller.startswith("server.py"), (
            "the profile write is reachable from %s. It must be invoked only from the "
            "write tools, never as a side effect of anything." % caller
        )


def test_no_scheduled_or_sync_path_can_reach_the_profile_write():
    """The modules that run on their own must not be able to write to him."""
    root = Path(__file__).resolve().parent.parent
    for name in ("scheduler.py", "sync.py", "alerts.py", "brief.py", "insight.py"):
        text = (root / "uplers_server" / name).read_text(encoding="utf-8")
        assert "profile_write" not in text
        assert "EP_PROFILE_UPSERT" not in text


async def test_the_local_sync_tool_still_writes_only_to_the_local_file(
    monkeypatch, make_profile, real_payload
):
    """The two directions must not have leaked into each other.

    `uplers_sync_profile_from_uplers` pulls Uplers -> local.
    `uplers_update_profile` pushes local intent -> Uplers. Only the second may
    ever send a request, and only when a caller confirms it.
    """
    make_profile()
    calls = wire_talent(monkeypatch, profile_then_upsert(real_payload))

    await server.uplers_sync_profile_from_uplers(confirm=True)

    assert writes(calls) == []
    assert [call.url.path for call in calls] == [PROFILE_PATH]
