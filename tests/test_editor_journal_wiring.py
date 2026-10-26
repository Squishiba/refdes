"""Wire `editor_journal` into the editor save path (backlog finding 15a).

The module (`src/refdes/editor_journal.py`, #367) exists and its own suite
passes; this module pins the WIRING, the acceptance boundary of
docs/design/browser-editor.md: "If the process is killed between two
replacements, a visible `.refdes/editor-transaction/` is left behind, and all
project-loading commands are refused until `refdes recover` restores it."

Every crash test is the same shape: inject a hard stop (an `OSError` rising
out of the write section, the shape of a kill between the syscall and the
return) at one journal step, then assert `refdes recover` yields the COMPLETE
old state -- never a half-apply. The no-crash tests pin the steady state:
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
        editor_journal.Entry(
            rel, (root / rel).read_bytes(), b"journal replacement, never landed\n"
        )
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


def test_crash_after_create_before_the_ledger_recovers_old_state(
    tmp_path, monkeypatch
):
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
    if editor_journal.pending(str(tmp_path)) is not None:
        assert run_cli(tmp_path, "recover") == 0
        assert (tmp_path / "items" / "reqs.yaml").read_bytes() == before
    assert "Half-created." not in (tmp_path / "items" / "reqs.yaml").read_text()


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
    assert cli_mod.main(["schema", "--json"]) == 2  # today: no project found
    captured = capsys.readouterr()
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
    # replacement landed on disk, the journal never cleared
    reqs.write_bytes(b"rewritten by a save that died\n")

    assert run_cli(tmp_path, "recover") == 0
    captured = capsys.readouterr()
    assert reqs.read_bytes() == original
    assert "items/reqs.yaml" in captured.out
    assert editor_journal.pending(str(tmp_path)) is None


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


@pytest.mark.skipif(os.name == "nt", reason="POSIX permissions")
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
    notes.write_bytes(notes.read_bytes().replace(b"\n", b"\r\n"))
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
