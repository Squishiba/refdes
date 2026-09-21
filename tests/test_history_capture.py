"""Phase H2: capture at the `follows:` edge, announced.

docs/design/living-notes-plan.md §H2 and docs/design/living-notes.md §2.
When a writable load freezes a bare `follows:` edge, it also captures a
`followed` event holding the predecessor's snapshot into
`.refdes/history/` and prints `captured LOG-001: LOG-002 now follows it`
on stderr. The freeze itself behaves exactly as before; `--no-write`
reaches none of this (the tree-hash coverage lives in
tests/test_no_write.py). The schema here declares `follows:` by hand --
`hardware@3` does not declare it yet -- so every project in this file is
the "any project whose schema declares it" case, the same convention as
tests/test_chains.py.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil

from conftest import write_project_config

from refdes import build as build_mod
from refdes import cli as cli_mod
from refdes import history, loader

FOLLOWS_SCHEMA = """\
site: { title: Capture Test, out: ../site_out_capture }
id: { width: 3, ledger: .refdes/ids.yaml }
link_types:
  follows: { inverse: followed_by, label: Follows }
types:
  log:
    prefix: LOG
    append_only: true
    fields:
      summary: { type: text, required: true }
    links:
      follows: [log]
"""

TWO = (
    "defaults: { type: log }\n"
    "items:\n"
    "  - id: LOG-001\n    summary: First.\n"
    "  - id: LOG-002\n    summary: Second.\n    follows: [LOG-001]\n"
)


def _setup(tmp_path, items_yaml):
    write_project_config(tmp_path, FOLLOWS_SCHEMA)
    items = tmp_path / "items"
    items.mkdir(exist_ok=True)
    (items / "log.yaml").write_text(items_yaml, encoding="utf-8")
    return str(tmp_path / "refdes-project.yaml")


def _tree(root):
    """relpath -> sha256 for every file under `root`."""
    files = {}
    for dirpath, _dirnames, names in os.walk(str(root)):
        for name in names:
            path = os.path.join(dirpath, name)
            rel = os.path.relpath(path, str(root)).replace("\\", "/")
            with open(path, "rb") as fh:
                files[rel] = hashlib.sha256(fh.read()).hexdigest()
    return files


def _repoint_edge(path, new_target):
    """Rewrite the file's `follows:` line(s) to a bare target -- the author
    correcting a typo, or reverting an edge for the replay case."""
    lines = [
        "    follows: [%s]" % new_target
        if line.strip().startswith("follows:")
        else line
        for line in path.read_text(encoding="utf-8").splitlines()
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


# ------------------------------------------------------- the capture moment


def test_a_frozen_edge_captures_the_predecessor_and_announces(tmp_path, capsys):
    cfg = _setup(tmp_path, TWO)
    project, _stale = loader.load_tree(cfg, write=True)
    captured = capsys.readouterr()

    assert "captured LOG-001: LOG-002 now follows it" in captured.err
    events = history.load_events(str(tmp_path))
    assert len(events) == 1
    event = events[0]
    assert event["kind"] == "followed"
    assert event["item_key"] == project.item_by_id("LOG-001").key
    assert event["successor_key"] == project.item_by_id("LOG-002").key
    assert "occurred_at" not in event  # no clock: replay must be byte-identical

    snapshot = history.load_object(str(tmp_path), event["object"])
    assert snapshot["id"] == "LOG-001"
    assert snapshot["fields"]["summary"] == "First."
    assert snapshot["key"] == project.item_by_id("LOG-001").key


def test_the_announcement_never_pollutes_machine_output(tmp_path, capsys):
    """§H2 case two (VS Code's save refresh) and Q4: `index --compact`
    prints JSON only; the capture line is visible on stderr, never on the
    stdout the extension parses."""
    cfg = _setup(tmp_path, TWO)
    assert cli_mod.main(["-c", cfg, "index", "--compact"]) == 0
    captured = capsys.readouterr()
    json.loads(captured.out)  # parse-clean, as the extension requires
    assert "captured" not in captured.out
    assert "captured LOG-001: LOG-002 now follows it" in captured.err


def test_a_second_writable_load_writes_nothing_new(tmp_path, capsys):
    """§H2 case five (idempotence), end to end: the every-save load cannot
    accumulate duplicates, and prints nothing when it wrote nothing."""
    cfg = _setup(tmp_path, TWO)
    loader.load_tree(cfg, write=True)
    capsys.readouterr()
    before = _tree(tmp_path)

    loader.load_tree(cfg, write=True)
    captured = capsys.readouterr()
    assert _tree(tmp_path) == before
    assert "captured" not in captured.out + captured.err
    assert len(history.load_events(str(tmp_path))) == 1


# ------------------------------------------------------ the five §2 cases


def test_a_typo_corrected_on_the_next_save_writes_a_correction_event(tmp_path, capsys):
    """§H2 case one: the wrong predecessor keeps its event -- never deleted,
    never rewritten -- and the corrected edge adds a `followed-corrected`
    event naming what it supersedes."""
    cfg = _setup(
        tmp_path,
        TWO + "  - id: LOG-003\n    summary: The one actually meant.\n",
    )
    loader.load_tree(cfg, write=True)
    events_dir = tmp_path / ".refdes" / "history" / "events"
    original = history.load_events(str(tmp_path))[0]
    original_file = events_dir / f"{original['id']}.yaml"
    original_bytes = original_file.read_bytes()

    log = tmp_path / "items" / "log.yaml"
    _repoint_edge(log, "LOG-003")
    project, _stale = loader.load_tree(cfg, write=True)
    capsys.readouterr()

    events = history.load_events(str(tmp_path))
    assert len(events) == 2
    corrected = [e for e in events if e["kind"] == "followed-corrected"]
    assert len(corrected) == 1
    assert corrected[0]["item_key"] == project.item_by_id("LOG-003").key
    assert corrected[0]["successor_key"] == project.item_by_id("LOG-002").key
    assert original["item_key"] in corrected[0]["reason"]

    # The first event survives byte-identical: corrected, never erased.
    assert original_file.read_bytes() == original_bytes


def test_an_old_branch_replay_writes_the_identical_path_and_bytes(tmp_path):
    """§H2 case four: a checkout whose store lacks the event regenerates the
    same derived id, the same content-addressed object, and -- because H2
    capture writes no clock -- the identical bytes."""
    cfg = _setup(tmp_path, TWO)
    loader.load_tree(cfg, write=True)

    branch = tmp_path / "branch"
    shutil.copytree(str(tmp_path), str(branch))
    _repoint_edge(branch / "items" / "log.yaml", "LOG-001")
    shutil.rmtree(str(branch / ".refdes" / "history"))

    loader.load_tree(str(branch / "refdes-project.yaml"), write=True)
    assert _tree(branch / ".refdes" / "history") == _tree(
        tmp_path / ".refdes" / "history"
    )


def test_each_frozen_edge_captures_its_own_predecessor(tmp_path):
    """Two frozen edges in one load -- two events, each holding the snapshot
    of the predecessor that edge points at (freeze resolves a bare edge to
    the current tip, so a chain authored bare freezes as a chain)."""
    cfg = _setup(
        tmp_path,
        "defaults: { type: log }\n"
        "items:\n"
        "  - id: LOG-001\n    summary: Head.\n"
        "  - id: LOG-002\n    summary: Second.\n    follows: [LOG-001]\n"
        "  - id: LOG-003\n    summary: Third.\n    follows: [LOG-002]\n",
    )
    project, _stale = loader.load_tree(cfg, write=True)
    events = history.load_events(str(tmp_path))
    assert len(events) == 2
    assert {e["kind"] for e in events} == {"followed"}
    preds = {e["item_key"] for e in events}
    assert preds == {
        project.item_by_id("LOG-001").key,
        project.item_by_id("LOG-002").key,
    }
    assert len({e["object"] for e in events}) == 2


def test_a_merge_captures_both_parents_and_is_not_a_correction(tmp_path):
    """A merge entry names two live parents; both captures stand as plain
    `followed` events -- correction is only for a predecessor the successor
    no longer edges to."""
    cfg = _setup(
        tmp_path,
        "defaults: { type: log }\n"
        "items:\n"
        "  - id: LOG-001\n    summary: Root A.\n"
        "  - id: LOG-002\n    summary: Root B.\n"
        "  - id: LOG-003\n    summary: Merged.\n    follows: [LOG-001, LOG-002]\n",
    )
    loader.load_tree(cfg, write=True)
    events = history.load_events(str(tmp_path))
    assert len(events) == 2
    assert {e["kind"] for e in events} == {"followed"}
    assert len({e["item_key"] for e in events}) == 2


# ------------------------------------------- the transaction and the refusals


def test_a_failed_event_write_rolls_the_frozen_edge_back(tmp_path, monkeypatch):
    """The plan's transaction case the parse guard cannot catch: the rewrite
    parses fine and the *event* write is what fails -- the edge must not
    stay frozen without its event."""

    def boom(*args, **kwargs):
        raise OSError("the disk refused")

    monkeypatch.setattr(history, "append_event", boom)
    cfg = _setup(tmp_path, TWO)
    project, _stale = loader.load_tree(cfg, write=True)

    assert any("rolled back" in str(d) for d in project.errors)
    text = (tmp_path / "items" / "log.yaml").read_text(encoding="utf-8")
    assert "follows: [LOG-001]" in text  # the authored bare spelling, restored
    events_dir = tmp_path / ".refdes" / "history" / "events"
    assert not (list(events_dir.glob("*.yaml")) if events_dir.is_dir() else [])
    objects_dir = tmp_path / ".refdes" / "history" / "objects"
    assert not (list(objects_dir.glob("*.yaml")) if objects_dir.is_dir() else [])


def test_a_sealed_entry_with_a_bare_edge_still_refuses_and_captures_nothing(
    tmp_path,
):
    """H2 must not silently change the sealed-entry refusal (that changes in
    H5): the warning stands, the edge stays bare, and no event is written."""
    cfg = _setup(
        tmp_path,
        "defaults: { type: log }\n"
        "items:\n"
        "  - id: LOG-001\n    summary: First.\n"
        "  - id: LOG-002\n    summary: Second.\n",
    )
    project, _stale = loader.load_tree(cfg, write=True)
    build_mod.build(project, seal_write=True, reseal=False)

    log = tmp_path / "items" / "log.yaml"
    lines = log.read_text(encoding="utf-8").splitlines()
    edited = []
    for line in lines:
        edited.append(line)
        if line.strip() == "summary: Second.":
            edited.append("    follows: [LOG-001]")
    assert len(edited) == len(lines) + 1
    log.write_text("\n".join(edited) + "\n", encoding="utf-8")
    project, _stale = loader.load_tree(cfg, write=True)

    assert any("already sealed" in d.message for d in project.warnings)
    assert not (tmp_path / ".refdes" / "history").exists()
    assert "follows: [LOG-001]" in log.read_text(encoding="utf-8")


def test_a_project_without_follows_never_gains_a_history_directory(tmp_path):
    """A project that never uses history gains no directory at all."""
    cfg = _setup(
        tmp_path,
        "defaults: { type: log }\nitems:\n  - id: LOG-001\n    summary: Alone.\n",
    )
    loader.load_tree(cfg, write=True)
    assert not (tmp_path / ".refdes" / "history").exists()
