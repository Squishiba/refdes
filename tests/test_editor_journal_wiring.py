"""Wire `editor_journal` into the editor save path (backlog finding 15a).

The module (`src/refdes/editor_journal.py`, #367) exists and its own suite
passes; this module pins the WIRING, the acceptance boundary of
docs/design/browser-editor.md: "If the process is killed between two
replacements, a visible `.refdes/editor-transaction/` is left behind, and all
project-loading commands are refused until `refdes recover` restores it."

The crash tests come in two shapes and they pin different things. The
handled shape injects an `OSError` at one journal step: that is a write
failure the save path CATCHES, and the test pins the refusal -- nothing
written, the journal kept or cleared as the shape demands. The true-kill
shape injects a `BaseException` (the hard kill that passes no handler):
the journal must stand, and `refdes recover` must yield the COMPLETE old
state -- never a half-apply. The no-crash tests pin the steady state:
the journal exists exactly during the write and is gone after it, so a
differential of a normal save is byte-identical to the pre-wiring world.

Journal scope is the item files: `editor_journal.begin` refuses entries
landing inside `.refdes` (its control namespace), so `.refdes/citations.yaml`
and `.refdes/ids.yaml` are NOT journaled; a crash between the lockfile write
and the item write leaves the pin inert, and recover restores the item half.
"""

from __future__ import annotations

import json
import os
import threading

import pytest
from serve_support import make_project, snapshot_tree
from test_serve_edit_keyless_handle import Api, save
from test_serve_sources import fetch, make_root
from test_serve_sources_accept import EFF, RAIL, calc_body, pin

from refdes import cli as cli_mod
from refdes import editor_journal
from refdes.serve import edit as edit_mod

CRASH = "simulated crash: killed between the syscall and the return"
JOURNAL_REPLACEMENT = b"journal replacement, never landed\n"


def config_of(root):
    return str(root / "refdes-project.yaml")


def run_cli(root, *argv) -> int:
    return cli_mod.main(["-c", config_of(root), *argv])


def content_tree(root):
    """Every project-content hash, journal dir excluded (a test that journals
    by hand adds files under `.refdes/editor-transaction/` on purpose)."""
    return {
        rel: digest
        for rel, digest in snapshot_tree(root).items()
        if not rel.startswith(".refdes/editor-transaction")
    }


def journal_the_project(root, *rels: str) -> str:
    """Arm a journal the way a save does, entries against the live bytes."""
    entries = [
        editor_journal.Entry(rel, (root / rel).read_bytes(), JOURNAL_REPLACEMENT)
        for rel in (rels or ("items/reqs.yaml",))
    ]
    return editor_journal.begin(str(root), entries)


def patch_replace_crash(monkeypatch, *, at_call: int | None = None):
    """Make the atomic replace raise -- the kill shape. `at_call` (1-based)
    lets a multi-write route crash on its Nth replace and land the rest."""
    real = edit_mod._atomic_replace
    calls = []

    def patched(path, payload, expected=None):
        calls.append(path)
        if at_call is None or len(calls) == at_call:
            raise OSError(CRASH)
        return real(path, payload, expected)

    monkeypatch.setattr(edit_mod, "_atomic_replace", patched)
    return calls


# ---------------------------------------------------------- steady state


def test_save_journals_during_the_replace_and_clears_after(tmp_path, monkeypatch):
    """The journal is visible to the exact window that is half-applied on a
    kill -- the replace -- and is gone the moment the save is reported."""
    make_project(tmp_path)
    client = Api(tmp_path)
    _status, view = client.get("/api/item/REQ-001")
    seen = []
    real = edit_mod._atomic_replace

    def spy(path, payload, expected=None):
        seen.append(editor_journal.pending(str(tmp_path)))
        return real(path, payload, expected)

    monkeypatch.setattr(edit_mod, "_atomic_replace", spy)

    status, payload = save(client, "REQ-001", revision=view["edit"]["file_revision"])
    assert status == 200, payload
    assert payload["kind"] == "applied"
    assert seen and all(tx is not None for tx in seen), (
        "no journal was armed while the replacement ran"
    )
    assert editor_journal.pending(str(tmp_path)) is None
    assert not (tmp_path / ".refdes" / "editor-transaction").exists()


def test_create_journals_during_the_write_and_clears_after(tmp_path, monkeypatch):
    make_project(tmp_path)
    client = Api(tmp_path)
    seen = []
    real = edit_mod._atomic_replace

    def spy(path, payload, expected=None):
        seen.append(editor_journal.pending(str(tmp_path)))
        return real(path, payload, expected)

    monkeypatch.setattr(edit_mod, "_atomic_replace", spy)

    status, payload = client.post(
        "/api/items/create", {"type": "requirement", "fields": {"text": "Journalled."}}
    )
    assert status == 200, payload
    assert payload["kind"] == "created"
    assert seen and all(tx is not None for tx in seen)
    assert editor_journal.pending(str(tmp_path)) is None


# ------------------------------------------------------------ crash points


def test_crash_between_journal_and_replacement_recovers_old_state(
    tmp_path, monkeypatch, capsys
):
    make_project(tmp_path)
    client = Api(tmp_path)
    _status, view = client.get("/api/item/REQ-001")
    before = (tmp_path / "items" / "reqs.yaml").read_bytes()
    patch_replace_crash(monkeypatch)

    status, payload = save(client, "REQ-001", revision=view["edit"]["file_revision"])
    assert status == 422, payload
    assert editor_journal.pending(str(tmp_path)) is not None, (
        "a kill after journaling left no journal: the save wrote before journaling"
    )

    assert run_cli(tmp_path, "recover") == 0
    assert (tmp_path / "items" / "reqs.yaml").read_bytes() == before
    assert editor_journal.pending(str(tmp_path)) is None


def test_crash_after_replacement_before_clearing_recovers_old_state(
    tmp_path, monkeypatch, capsys
):
    make_project(tmp_path)
    client = Api(tmp_path)
    _status, view = client.get("/api/item/REQ-001")
    before = (tmp_path / "items" / "reqs.yaml").read_bytes()

    def boom(*args, **kwargs):
        raise OSError(CRASH)

    monkeypatch.setattr(editor_journal, "complete", boom)

    status, payload = save(client, "REQ-001", revision=view["edit"]["file_revision"])
    assert status == 200, payload
    assert "refdes recover" in payload["message"], payload
    assert editor_journal.pending(str(tmp_path)) is not None

    assert run_cli(tmp_path, "recover") == 0
    assert (tmp_path / "items" / "reqs.yaml").read_bytes() == before
    assert editor_journal.pending(str(tmp_path)) is None


def test_a_replaced_file_write_failure_clears_the_journal(tmp_path, monkeypatch):
    """The write's REAL failure branch (a returned failure string, the
    shape `os.replace` failure takes through `_atomic_replace`): the
    journal describes a write that landed nowhere, so the refusal clears
    it -- a survival would gate the project on a transaction that needs
    no recovery."""
    make_project(tmp_path)
    client = Api(tmp_path)
    _status, view = client.get("/api/item/REQ-001")
    before = (tmp_path / "items" / "reqs.yaml").read_bytes()
    monkeypatch.setattr(
        edit_mod, "_atomic_replace", lambda *args, **kwargs: "simulated write failure"
    )

    status, payload = save(client, "REQ-001", revision=view["edit"]["file_revision"])
    assert status == 422, payload
    assert payload["kind"] == "refused"
    assert "simulated write failure" in payload["reason"]
    assert (tmp_path / "items" / "reqs.yaml").read_bytes() == before
    assert editor_journal.pending(str(tmp_path)) is None


def test_a_hard_kill_after_journaling_leaves_the_journal_for_recover(
    tmp_path, monkeypatch
):
    """The kill shape the design names: the process dies between arming
    the journal and the replacement (an uncatchable signal, not a
    handled `OSError`). The journal survives with the save's originals,
    and `refdes recover` yields the complete old state."""

    class Killed(BaseException):
        pass

    make_project(tmp_path)
    client = Api(tmp_path)
    _status, view = client.get("/api/item/REQ-001")
    before = (tmp_path / "items" / "reqs.yaml").read_bytes()

    def crash(*args, **kwargs):
        raise Killed(CRASH)

    monkeypatch.setattr(edit_mod, "_atomic_replace", crash)
    with pytest.raises(Killed):
        save(client, "REQ-001", revision=view["edit"]["file_revision"])
    assert editor_journal.pending(str(tmp_path)) is not None

    assert run_cli(tmp_path, "recover") == 0
    assert (tmp_path / "items" / "reqs.yaml").read_bytes() == before
    assert editor_journal.pending(str(tmp_path)) is None


def test_crash_between_the_pair_lands_the_old_item_state(tmp_path, monkeypatch):
    """The accept save's two replaces (lockfile, then item): a kill between
    them is the design's named scenario -- journal visible, recover restores
    the item's complete old state."""
    root = make_root(tmp_path)
    fetch(root)
    client = Api(root)
    _status, view = client.get("/api/item/DEC-001")
    before = (root / "items" / "decisions.yaml").read_bytes()
    patch_replace_crash(monkeypatch, at_call=2)

    status, payload = client.post(
        "/api/item/DEC-001/edit",
        {
            "op": "set_body",
            "text": calc_body(RAIL, EFF),
            "pin": pin("eff", name="eff"),
            "expected_revision": view["edit"]["file_revision"],
        },
    )
    assert status == 422, payload
    assert editor_journal.pending(str(root)) is not None

    assert run_cli(root, "recover") == 0
    assert (root / "items" / "decisions.yaml").read_bytes() == before
    assert editor_journal.pending(str(root)) is None


def test_create_reserve_failure_rolls_back_and_clears_the_journal(tmp_path, monkeypatch):
    """The create's own rollback branch: the ledger write fails, the file
    rolls back, the journal (a record of a write that no longer exists)
    goes with it, and nothing half-created survives."""
    make_project(tmp_path)
    client = Api(tmp_path)
    before = (tmp_path / "items" / "reqs.yaml").read_bytes()

    def boom(*args, **kwargs):
        raise OSError(CRASH)

    monkeypatch.setattr(edit_mod.ids, "reserve_id", boom)

    status, payload = client.post(
        "/api/items/create", {"type": "requirement", "fields": {"text": "Half-created."}}
    )
    assert status == 422, payload
    assert editor_journal.pending(str(tmp_path)) is None
    assert (tmp_path / "items" / "reqs.yaml").read_bytes() == before
    assert "Half-created." not in (tmp_path / "items" / "reqs.yaml").read_text()


def test_create_with_a_failing_rollback_leaves_the_journal_for_recover(
    tmp_path, monkeypatch
):
    """The unconditional recovery story: the create's bytes are on disk,
    the ledger write fails, AND the rollback cannot undo the file. The
    journal must survive -- it is the only record of the old bytes -- the
    refusal must name `refdes recover`, and recover must yield the
    complete old state."""
    make_project(tmp_path)
    client = Api(tmp_path)
    before = (tmp_path / "items" / "reqs.yaml").read_bytes()

    def boom(*args, **kwargs):
        raise OSError(CRASH)

    monkeypatch.setattr(edit_mod.ids, "reserve_id", boom)
    monkeypatch.setattr(edit_mod, "_rollback", lambda path, original: False)

    status, payload = client.post(
        "/api/items/create", {"type": "requirement", "fields": {"text": "Half-created."}}
    )
    assert status == 422, payload
    assert payload["kind"] == "refused"
    assert "refdes recover" in payload["reason"], payload
    assert editor_journal.pending(str(tmp_path)) is not None, (
        "the create cleared the journal over a file it could not roll back"
    )

    assert run_cli(tmp_path, "recover") == 0
    assert (tmp_path / "items" / "reqs.yaml").read_bytes() == before
    assert "Half-created." not in (tmp_path / "items" / "reqs.yaml").read_text()
    assert editor_journal.pending(str(tmp_path)) is None


def test_a_new_file_create_crash_before_the_link_leaves_an_inert_journal(
    tmp_path, monkeypatch
):
    """The `original=None` journal entry (new file, `_atomic_create`): the
    kill after the journal lands leaves the entry naming a file that did
    not exist before, and recover's job is to remove it. Here the create
    died before the file appeared, so recovery is the inert pass -- it
    must still clear the journal, not choke on the absent file."""
    make_project(tmp_path)
    client = Api(tmp_path)
    target = tmp_path / "items" / "new-requirements.md"

    def crash(*args, **kwargs):
        raise OSError(CRASH)

    monkeypatch.setattr(edit_mod, "_atomic_create", crash)
    status, payload = client.post(
        "/api/items/create",
        {
            "type": "requirement",
            "fields": {"text": "New file."},
            "destination": "items/new-requirements.md",
        },
    )
    assert status == 422, payload
    assert not target.exists()
    assert editor_journal.pending(str(tmp_path)) is not None, (
        "the create's write was not journaled"
    )
    manifest = json.loads(
        (tmp_path / ".refdes" / "editor-transaction" / "manifest.json").read_text()
    )
    entry = manifest["entries"][0]
    assert entry["path"] == "items/new-requirements.md"
    assert entry["existed"] is False

    assert run_cli(tmp_path, "recover") == 0
    assert not target.exists()
    assert editor_journal.pending(str(tmp_path)) is None


def test_created_file_stands_after_a_hard_kill_and_recover_removes_it(
    tmp_path, monkeypatch
):
    """The half-apply of a create, recovered: the new file is on disk, the
    journal recorded it as not-existing-before, and `refdes recover`
    removes it -- the project returns to the complete pre-create state."""

    class Killed(BaseException):
        pass

    make_project(tmp_path)
    client = Api(tmp_path)
    target = tmp_path / "items" / "new-requirements.md"

    def crash(*args, **kwargs):
        raise Killed(CRASH)

    monkeypatch.setattr(edit_mod.ids, "reserve_id", crash)
    with pytest.raises(Killed):
        client.post(
            "/api/items/create",
            {
                "type": "requirement",
                "fields": {"text": "Half-created."},
                "destination": "items/new-requirements.md",
            },
        )
    assert target.exists(), "the create's file is not on disk: the shape is wrong"
    assert editor_journal.pending(str(tmp_path)) is not None

    assert run_cli(tmp_path, "recover") == 0
    assert not target.exists()
    assert editor_journal.pending(str(tmp_path)) is None


def test_created_save_warns_and_keeps_the_journal_when_complete_fails(
    tmp_path, monkeypatch
):
    """`Created.journal_warning`: the create landed, the journal could not
    be cleared, and the response must say so -- the project is now gated
    and `refdes recover` (which deletes the created file; the id stays
    reserved) is the way out."""
    make_project(tmp_path)
    client = Api(tmp_path)

    def boom(*args, **kwargs):
        raise OSError(CRASH)

    monkeypatch.setattr(editor_journal, "complete", boom)
    status, payload = client.post(
        "/api/items/create", {"type": "requirement", "fields": {"text": "Journalled."}}
    )
    assert status == 200, payload
    assert payload["kind"] == "created"
    assert "refdes recover" in payload["message"], payload
    assert editor_journal.pending(str(tmp_path)) is not None


# ------------------------------------------------------- refusal to load


def test_save_refused_while_journal_present(tmp_path):
    make_project(tmp_path)
    client = Api(tmp_path)
    _status, view = client.get("/api/item/REQ-001")
    tx = journal_the_project(tmp_path)

    status, payload = save(client, "REQ-001", revision=view["edit"]["file_revision"])
    assert status == 422, payload
    assert payload["kind"] == "refused"
    assert "refdes recover" in payload["reason"]
    assert "refdes recover" in payload["message"]
    assert (tmp_path / "items" / "reqs.yaml").read_text().count("draft") == 0
    assert editor_journal.pending(str(tmp_path)) == tx


@pytest.mark.parametrize(
    "argv",
    [
        ["check"],
        ["--no-write", "check"],
        ["build"],
        ["index"],
        ["ls"],
        ["id"],
        ["audit"],
        ["fetch"],
        ["schema", "--json"],
        ["rename", "mapping.yaml"],
    ],
)
def test_project_loading_commands_refuse_while_journal_present(tmp_path, argv, capsys):
    make_project(tmp_path)
    tx = journal_the_project(tmp_path)
    before = content_tree(tmp_path)

    rc = run_cli(tmp_path, *argv)
    captured = capsys.readouterr()
    assert rc == 2, (argv, rc, captured.out, captured.err)
    assert "refdes recover" in captured.err, (argv, captured)
    assert tx in captured.err
    assert content_tree(tmp_path) == before


def test_commands_without_a_project_are_unaffected(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    cli_mod.main(["schema", "--json"])
    captured = capsys.readouterr()
    # the gate adds no refusal of its own: with no project there is no
    # journal to check, and the command's own error speaks
    assert "refdes recover" not in captured.err


def test_serve_refuses_to_start_while_journal_present(tmp_path):
    make_project(tmp_path)
    journal_the_project(tmp_path)
    result = {}

    def drive():
        result["rc"] = run_cli(tmp_path, "serve", "--no-open")

    thread = threading.Thread(target=drive, daemon=True)
    thread.start()
    thread.join(10)
    assert not thread.is_alive(), "serve started its server over a pending journal"
    assert result["rc"] == 2


# ---------------------------------------------------------------- recover


def test_recover_on_a_clean_project_reports_nothing(tmp_path, capsys):
    make_project(tmp_path)
    before = content_tree(tmp_path)
    assert run_cli(tmp_path, "recover") == 0
    assert "nothing to recover" in capsys.readouterr().out
    assert content_tree(tmp_path) == before


def test_recover_restores_every_journaled_entry(tmp_path, capsys):
    make_project(tmp_path)
    reqs = tmp_path / "items" / "reqs.yaml"
    original = reqs.read_bytes()
    journal_the_project(tmp_path, "items/reqs.yaml")
    # the journal armed, simulate the half-apply it guards against: the
    # recorded replacement landed on disk, the journal never cleared
    reqs.write_bytes(JOURNAL_REPLACEMENT)

    assert run_cli(tmp_path, "recover") == 0
    captured = capsys.readouterr()
    assert reqs.read_bytes() == original
    assert "recovered editor transaction" in captured.out
    assert "restored items/reqs.yaml" in captured.out
    assert editor_journal.pending(str(tmp_path)) is None


def test_recover_refuses_an_unparseable_manifest_and_keeps_the_journal(tmp_path, capsys):
    """The manifest is published atomically, last: bytes that do not parse
    are damage, not a mid-begin crash, and the journal is the only
    rollback copy. `recover` must refuse with 2, touch nothing, keep the
    evidence, and leave the gate refusing."""
    make_project(tmp_path)
    journal_the_project(tmp_path)
    manifest = tmp_path / ".refdes" / "editor-transaction" / "manifest.json"
    manifest.write_bytes(b"\x00\x01not json at all")
    reqs = tmp_path / "items" / "reqs.yaml"
    reqs.write_bytes(JOURNAL_REPLACEMENT)  # the half-apply it used to describe

    assert run_cli(tmp_path, "recover") == 2
    captured = capsys.readouterr()
    assert "recover refused" in captured.err
    assert reqs.read_bytes() == JOURNAL_REPLACEMENT, "recovery touched the live file"
    assert manifest.read_bytes() == b"\x00\x01not json at all", "the evidence was deleted"
    assert editor_journal.pending(str(tmp_path)) == "unknown", "the gate must keep refusing"


def test_recover_refuses_a_live_file_the_transaction_does_not_describe(tmp_path, capsys):
    """The documented replacement check, through the CLI: a live file
    matching neither recorded hash changed outside the transaction, and
    restoring over it is data loss. Refuse, change nothing, keep the
    journal -- the gate keeps every command out until a human decides."""
    make_project(tmp_path)
    journal_the_project(tmp_path, "items/reqs.yaml")
    reqs = tmp_path / "items" / "reqs.yaml"
    outside = b"written by a writer outside the transaction\n"
    reqs.write_bytes(outside)

    assert run_cli(tmp_path, "recover") == 2
    captured = capsys.readouterr()
    assert "recover refused" in captured.err
    assert "items/reqs.yaml" in captured.err
    assert reqs.read_bytes() == outside
    assert editor_journal.pending(str(tmp_path)) is not None

def test_recover_clears_a_journal_directory_that_recorded_nothing(tmp_path, capsys):
    """The inert shape: begin renames the journal in AFTER writing its
    manifest, so a directory with no manifest is a crash before any live
    file was touched. Clear it, and report it honestly -- not as the
    recovery of a transaction named 'unknown'."""
    make_project(tmp_path)
    journal = tmp_path / ".refdes" / "editor-transaction"
    journal.mkdir(parents=True)
    before = content_tree(tmp_path)

    assert run_cli(tmp_path, "recover") == 0
    captured = capsys.readouterr()
    assert "journal is cleared" in captured.out
    assert "unknown" not in captured.out
    assert not journal.exists()
    assert content_tree(tmp_path) == before


def test_recover_refuses_a_corrupt_journal_and_keeps_it(tmp_path, capsys):
    make_project(tmp_path)
    journal_the_project(tmp_path)
    manifest = tmp_path / ".refdes" / "editor-transaction" / "manifest.json"
    data = json.loads(manifest.read_text())
    data["entries"][0]["replacement_sha256"] = "not-a-hash"
    manifest.write_text(json.dumps(data))
    before = content_tree(tmp_path)

    rc = run_cli(tmp_path, "recover")
    captured = capsys.readouterr()
    assert rc == 2
    assert "recover refused" in captured.err
    assert editor_journal.pending(str(tmp_path)) is not None
    assert content_tree(tmp_path) == before


def test_recover_under_no_write_refuses_and_touches_nothing(tmp_path, capsys):
    make_project(tmp_path)
    journal_the_project(tmp_path)
    before = content_tree(tmp_path)

    rc = cli_mod.main(["--no-write", "-c", config_of(tmp_path), "recover"])
    captured = capsys.readouterr()
    assert rc == 2
    assert "--no-write" in captured.err
    assert content_tree(tmp_path) == before
    assert editor_journal.pending(str(tmp_path)) is not None


# ---------------------------------------------- journal-write safety nets


def test_readonly_commands_never_create_a_journal(tmp_path):
    make_project(tmp_path)
    journal_dir = tmp_path / ".refdes" / "editor-transaction"
    for argv in (
        ["check"],
        ["--no-write", "check"],
        ["--no-write", "build"],
        ["--no-write", "index"],
        ["ls"],
        ["schema", "--json"],
        ["fetch"],
    ):
        rc = run_cli(tmp_path, *argv)
        assert rc == 0, (argv, rc)
        assert editor_journal.pending(str(tmp_path)) is None
        assert not journal_dir.exists()


def test_readonly_serve_save_never_creates_a_journal(tmp_path):
    make_project(tmp_path)
    client = Api(tmp_path, read_only=True)
    _status, view = client.get("/api/item/REQ-001")
    status, payload = save(client, "REQ-001", revision=view["edit"]["file_revision"])
    assert status == 403, payload
    assert editor_journal.pending(str(tmp_path)) is None
    assert not (tmp_path / ".refdes" / "editor-transaction").exists()


@pytest.mark.skipif(
    os.name == "nt" or (hasattr(os, "geteuid") and os.geteuid() == 0),
    reason="POSIX permissions, and chmod does not deny writes to root",
)
def test_save_refused_when_the_journal_directory_is_unwritable(tmp_path):
    make_project(tmp_path)
    client = Api(tmp_path)
    _status, view = client.get("/api/item/REQ-001")
    before = (tmp_path / "items" / "reqs.yaml").read_bytes()
    control = tmp_path / ".refdes"
    control.chmod(0o500)
    try:
        status, payload = save(
            client, "REQ-001", revision=view["edit"]["file_revision"]
        )
    finally:
        control.chmod(0o700)
    assert status == 422, payload
    assert payload["kind"] == "refused"
    assert "journal" in payload["reason"]
    # the refusal quotes the operating system's own error, which names the
    # control directory: the write-route scrubber must have made that
    # project-relative before the response left (serve/api.py `_write_outcome`)
    assert str(tmp_path) not in json.dumps(payload)
    assert (tmp_path / "items" / "reqs.yaml").read_bytes() == before
    assert not (control / "editor-transaction").exists()


def test_journal_refusal_response_has_no_absolute_root(tmp_path):
    make_project(tmp_path)
    client = Api(tmp_path)
    _status, view = client.get("/api/item/REQ-001")
    journal_the_project(tmp_path)

    status, payload = save(client, "REQ-001", revision=view["edit"]["file_revision"])
    assert status == 422, payload

    def walk(value):
        if isinstance(value, str):
            assert str(tmp_path) not in value and str(tmp_path).replace("\\", "/") not in value
        elif isinstance(value, dict):
            for item in value.values():
                walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)

    walk(payload)


# ------------------------------------------------------------ CRLF bytes


def test_crlf_bytes_survive_the_journal_and_recover(tmp_path, monkeypatch):
    make_project(tmp_path)
    notes = tmp_path / "items" / "notes.md"
    # normalize first: the fixture's write_text already emits \r\n on
    # Windows, and doubling them breaks the item's front-matter parsing
    notes.write_bytes(
        notes.read_bytes().replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")
    )
    client = Api(tmp_path)
    _status, view = client.get("/api/item/REQ-010")
    original = notes.read_bytes()
    assert b"\r\n" in original
    captured = []
    real_begin = editor_journal.begin

    def spy(root, entries):
        captured.extend(entries)
        return real_begin(root, entries)

    monkeypatch.setattr(editor_journal, "begin", spy)

    def boom(*args, **kwargs):
        raise OSError(CRASH)

    monkeypatch.setattr(editor_journal, "complete", boom)
    status, payload = save(
        client,
        "REQ-010",
        field="text",
        value="Rewritten.",
        revision=view["edit"]["file_revision"],
    )
    assert status == 200, payload
    assert captured and b"\r\n" in captured[0].original
    assert captured[0].original == original

    assert run_cli(tmp_path, "recover") == 0
    assert notes.read_bytes() == original


# ------------------------------------------------------------ concurrency


def test_concurrent_saves_serialize_and_leave_no_journal(tmp_path):
    make_project(tmp_path)
    refs = [("REQ-001", "status", "draft"), ("REQ-010", "text", "Concurrent.")]
    revisions = {}
    for ref, _field, _value in refs:
        _status, view = Api(tmp_path).get(f"/api/item/{ref}")
        revisions[ref] = view["edit"]["file_revision"]

    outcomes = []

    def worker(ref, field, value):
        client = Api(tmp_path)
        outcomes.append(save(client, ref, field=field, value=value, revision=revisions[ref]))

    threads = [
        threading.Thread(target=worker, args=(ref, field, value))
        for ref, field, value in refs
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(15)
        assert not thread.is_alive()

    statuses = [status for status, _payload in outcomes]
    assert statuses == [200, 200], outcomes
    assert editor_journal.pending(str(tmp_path)) is None
    assert not (tmp_path / ".refdes" / "editor-transaction").exists()
    assert "draft" in (tmp_path / "items" / "reqs.yaml").read_text()
    assert "Concurrent." in (tmp_path / "items" / "notes.md").read_text()


# ------------------------------------------------------- arm refusals (paths)
#
# `editor_journal.begin` classifies entry paths that it must never journal:
# a Windows device name, a colon, a path escaping the root through a
# symlink. It refuses with `ValueError`, and the wiring must translate that
# into the same clean 422 refusal every other arm failure gets -- a save
# that RAISES breaks the values-only contract of `apply_edit`/`create_item`
# and reaches the browser as a dead connection, not a refusal.

CON_FILE = (
    "defaults: { type: requirement, board: board-a }\n"
    "items:\n"
    "  - id: REQ-099\n"
    "    text: An item file whose name is a Windows device name.\n"
)

COLON_MD = (
    "---\n"
    "id: REQ-098\n"
    "type: requirement\n"
    "board: board-a\n"
    "text: An item file whose name carries a colon.\n"
    "---\n"
)


def test_a_device_name_item_file_refuses_the_save_cleanly(tmp_path):
    make_project(tmp_path)
    (tmp_path / "items" / "con.yaml").write_text(CON_FILE, encoding="utf-8")
    client = Api(tmp_path)
    _status, view = client.get("/api/item/REQ-099")
    before = content_tree(tmp_path)

    status, payload = save(client, "REQ-099", revision=view["edit"]["file_revision"])
    assert status == 422, payload
    assert payload["kind"] == "refused", payload
    assert "journal" in payload["reason"], payload
    assert content_tree(tmp_path) == before
    assert editor_journal.pending(str(tmp_path)) is None


def test_a_colon_in_the_item_file_name_refuses_the_save_cleanly(tmp_path):
    make_project(tmp_path)
    (tmp_path / "items" / "vin:min.md").write_text(COLON_MD, encoding="utf-8")
    client = Api(tmp_path)
    _status, view = client.get("/api/item/REQ-098")
    before = content_tree(tmp_path)

    status, payload = save(client, "REQ-098", revision=view["edit"]["file_revision"])
    assert status == 422, payload
    assert payload["kind"] == "refused", payload
    assert "journal" in payload["reason"], payload
    assert content_tree(tmp_path) == before
    assert editor_journal.pending(str(tmp_path)) is None


def test_a_symlinked_items_directory_refuses_the_save_cleanly(tmp_path):
    """The item file resolves INSIDE the root lexically and OUTSIDE it
    through a symlinked `items/`: `begin` refuses to journal it, and the
    save -- which would write through the link, outside the root -- must
    be refused with nothing written, not raised."""
    make_project(tmp_path)
    client = Api(tmp_path)
    _status, view = client.get("/api/item/REQ-001")
    before = (tmp_path / "items" / "reqs.yaml").read_bytes()
    outside = tmp_path.parent / f"{tmp_path.name}-outside"
    (tmp_path / "items").rename(outside)
    (tmp_path / "items").symlink_to(outside, target_is_directory=True)

    status, payload = save(client, "REQ-001", revision=view["edit"]["file_revision"])
    assert status == 422, payload
    assert payload["kind"] == "refused", payload
    assert "journal" in payload["reason"], payload
    assert (outside / "reqs.yaml").read_bytes() == before
    assert editor_journal.pending(str(tmp_path)) is None


def test_a_create_into_a_symlinked_items_directory_refuses_cleanly(tmp_path):
    make_project(tmp_path)
    client = Api(tmp_path)
    outside = tmp_path.parent / f"{tmp_path.name}-outside"
    (tmp_path / "items").rename(outside)
    (tmp_path / "items").symlink_to(outside, target_is_directory=True)
    before = content_tree(tmp_path)

    status, payload = client.post(
        "/api/items/create",
        {
            "type": "requirement",
            "fields": {"text": "Outside the root."},
            "destination": "items/new-requirements.md",
        },
    )
    assert status == 422, payload
    assert payload["kind"] == "refused", payload
    assert "journal" in payload["reason"], payload
    assert not (outside / "new-requirements.md").exists()
    assert content_tree(tmp_path) == before
    assert editor_journal.pending(str(tmp_path)) is None


# ------------------------------------------- failure strings that LANDED
#
# `_atomic_replace` and `_atomic_create` document failure branches that
# return AFTER the write landed (the replace ran, the post-write check
# failed, the restore did not land; the linked file fails its re-read).
# Those failure strings describe a half-applied save: the journal is the
# only record of the old bytes and must NOT be cleared. The journal may
# be cleared on a failure string only when the live bytes say nothing
# landed -- that classification is what these tests pin.


def test_a_write_failure_after_the_write_landed_keeps_the_journal(tmp_path, monkeypatch):
    make_project(tmp_path)
    client = Api(tmp_path)
    _status, view = client.get("/api/item/REQ-001")
    before = (tmp_path / "items" / "reqs.yaml").read_bytes()
    real = edit_mod._atomic_replace

    def landed_failure(path, payload, expected=None):
        real(path, payload, expected)
        return (
            f"could not re-read {path} after the write: simulated, the "
            f"original bytes could not be restored, and {path} was left "
            "as it was found"
        )

    monkeypatch.setattr(edit_mod, "_atomic_replace", landed_failure)
    status, payload = save(client, "REQ-001", revision=view["edit"]["file_revision"])
    assert status == 422, payload
    assert payload["kind"] == "refused", payload
    assert "refdes recover" in payload["reason"], payload
    assert (tmp_path / "items" / "reqs.yaml").read_bytes() != before, (
        "the fixture's write did not land"
    )
    assert editor_journal.pending(str(tmp_path)) is not None, (
        "the journal was cleared over a write that landed"
    )

    assert run_cli(tmp_path, "recover") == 0
    assert (tmp_path / "items" / "reqs.yaml").read_bytes() == before
    assert editor_journal.pending(str(tmp_path)) is None


def test_a_write_failure_that_restored_the_original_clears_the_journal(
    tmp_path, monkeypatch
):
    """The boundary, pinned: a failure string whose restore DID land is a
    write that landed nowhere. The live bytes match the journaled
    original, so clearing is right -- a survival would gate the project
    on a transaction that needs no recovery."""
    make_project(tmp_path)
    client = Api(tmp_path)
    _status, view = client.get("/api/item/REQ-001")
    before = (tmp_path / "items" / "reqs.yaml").read_bytes()
    real = edit_mod._atomic_replace

    def restored_failure(path, payload, expected=None):
        real(path, payload, expected)
        real(path, before)
        return (
            f"could not re-read {path} after the write: simulated; the "
            "original bytes were restored"
        )

    monkeypatch.setattr(edit_mod, "_atomic_replace", restored_failure)
    status, payload = save(client, "REQ-001", revision=view["edit"]["file_revision"])
    assert status == 422, payload
    assert payload["kind"] == "refused", payload
    assert "refdes recover" not in payload["reason"], payload
    assert (tmp_path / "items" / "reqs.yaml").read_bytes() == before
    assert editor_journal.pending(str(tmp_path)) is None


def test_a_created_file_failure_after_the_link_landed_keeps_the_journal(
    tmp_path, monkeypatch
):
    make_project(tmp_path)
    client = Api(tmp_path)
    target = tmp_path / "items" / "new-requirements.md"
    real = edit_mod._atomic_create

    def landed_failure(path, payload):
        real(path, payload)
        return f"the bytes on disk after the write are not the bytes planned for {path}"

    monkeypatch.setattr(edit_mod, "_atomic_create", landed_failure)
    status, payload = client.post(
        "/api/items/create",
        {
            "type": "requirement",
            "fields": {"text": "Half-created."},
            "destination": "items/new-requirements.md",
        },
    )
    assert status == 422, payload
    assert payload["kind"] == "refused", payload
    assert "refdes recover" in payload["reason"], payload
    assert target.exists(), "the fixture's create did not land"
    assert editor_journal.pending(str(tmp_path)) is not None, (
        "the journal was cleared over a create that landed"
    )

    assert run_cli(tmp_path, "recover") == 0
    assert not target.exists()
    assert editor_journal.pending(str(tmp_path)) is None


# ------------------------------------ journal-clear failures on refusals
#
# The conflict shapes clear a journal that describes a write that landed
# nowhere -- correct -- but the clear is best-effort: when IT fails, the
# project is gated and the response must say so (the refusal reports
# "nothing written" while the next load refuses the whole project).


def test_a_conflict_names_a_journal_clear_that_failed(tmp_path, monkeypatch):
    make_project(tmp_path)
    client = Api(tmp_path)
    _status, view = client.get("/api/item/REQ-001")

    def boom(*args, **kwargs):
        raise OSError(CRASH)

    monkeypatch.setattr(editor_journal, "complete", boom)

    def moved(path, payload, expected=None):
        raise edit_mod._Moved("0" * 64)

    monkeypatch.setattr(edit_mod, "_atomic_replace", moved)
    status, payload = save(client, "REQ-001", revision=view["edit"]["file_revision"])
    assert status == 409, payload
    assert payload["kind"] == "conflict", payload
    assert "refdes recover" in payload["message"], payload


def test_a_moved_destination_refusal_names_the_journal_clear_failure(
    tmp_path, monkeypatch
):
    make_project(tmp_path)
    client = Api(tmp_path)

    def boom(*args, **kwargs):
        raise OSError(CRASH)

    monkeypatch.setattr(editor_journal, "complete", boom)
    monkeypatch.setattr(edit_mod, "CREATE_DESTINATION_ATTEMPTS", 1)

    def moved(path, payload, expected=None):
        raise edit_mod._Moved("0" * 64)

    monkeypatch.setattr(edit_mod, "_atomic_replace", moved)
    status, payload = client.post(
        "/api/items/create", {"type": "requirement", "fields": {"text": "Journalled."}}
    )
    assert status == 422, payload
    assert payload["kind"] == "refused", payload
    assert "kept changing" in payload["reason"], payload
    assert "refdes recover" in payload["reason"], payload


# -------------------------------------------------- crash-point matrix
#
# The acceptance boundary of docs/design/browser-editor.md, enumerated:
# every journaled write route (save, accept, create-append,
# create-new-md) x the two kill points around the write (journal armed
# and nothing landed / write landed and the journal not yet cleared).
# In every cell `refdes recover` must yield the COMPLETE old state of
# every JOURNALED file -- never a half-apply. Journal scope is the item
# files by design (begin refuses entries inside `.refdes`), so the
# lockfile pin and the id ledger are outside the matrix's assertion.

MATRIX_ROUTES = ["save", "accept", "create-append", "create-new-md"]
MATRIX_CRASHES = ["before-write", "after-write-before-clear"]


@pytest.mark.parametrize("crash", MATRIX_CRASHES)
@pytest.mark.parametrize("route", MATRIX_ROUTES)
def test_crash_point_matrix_recovers_a_complete_state(
    route, crash, tmp_path, monkeypatch, capsys
):
    def boom(*args, **kwargs):
        raise OSError(CRASH)

    journaled_rel = "items/reqs.yaml"
    if route == "save":
        make_project(tmp_path)
        client = Api(tmp_path)
        _status, view = client.get("/api/item/REQ-001")

        def drive():
            return save(
                client, "REQ-001", revision=view["edit"]["file_revision"]
            )
    elif route == "accept":
        root = make_root(tmp_path)
        fetch(root)
        client = Api(root)
        _status, view = client.get("/api/item/DEC-001")
        journaled_rel = "items/decisions.yaml"

        def drive():
            return client.post(
                "/api/item/DEC-001/edit",
                {
                    "op": "set_body",
                    "text": calc_body(RAIL, EFF),
                    "pin": pin("eff", name="eff"),
                    "expected_revision": view["edit"]["file_revision"],
                },
            )
    elif route == "create-append":
        make_project(tmp_path)
        client = Api(tmp_path)

        def drive():
            return client.post(
                "/api/items/create",
                {"type": "requirement", "fields": {"text": "Matrix."}},
            )
    else:
        make_project(tmp_path)
        client = Api(tmp_path)

        def drive():
            return client.post(
                "/api/items/create",
                {
                    "type": "requirement",
                    "fields": {"text": "Matrix."},
                    "destination": "items/new-requirements.md",
                },
            )

    journaled = tmp_path / "items" / journaled_rel.split("/")[1]
    created = tmp_path / "items" / "new-requirements.md"
    before = journaled.read_bytes() if journaled.is_file() else None

    if crash == "after-write-before-clear":
        monkeypatch.setattr(editor_journal, "complete", boom)
        status, _payload = drive()
        assert status == 200, _payload
    elif route == "create-new-md":
        monkeypatch.setattr(edit_mod, "_atomic_create", boom)
        status, _payload = drive()
        assert status == 422, _payload
    elif route == "accept":
        patch_replace_crash(monkeypatch, at_call=2)
        status, _payload = drive()
        assert status == 422, _payload
    else:
        patch_replace_crash(monkeypatch)
        status, _payload = drive()
        assert status == 422, _payload

    assert editor_journal.pending(str(tmp_path)) is not None, (
        f"{route} x {crash}: the kill left no journal"
    )

    assert run_cli(tmp_path, "recover") == 0, capsys.readouterr()
    assert editor_journal.pending(str(tmp_path)) is None
    if route == "create-new-md":
        assert not created.exists(), f"{route} x {crash}: recover left the file"
    else:
        assert journaled.read_bytes() == before, (
            f"{route} x {crash}: the journaled file is not its complete old state"
        )
