"""Phase H4: `refdes history capture`, `redact`, and `migrate-seals`.

docs/design/living-notes-plan.md §H4. The author-facing commands for
everything the thread cannot supply: terminal and unthreaded notes, and
redaction. The sabotage posture of this file mirrors the plan's list:
each command's writes are exactly the documented files; `--no-write`
writes nothing anywhere (including under `.refdes/history/`); redaction
removes exactly the named content, leaves the store loadable with
consistent digests and event ids, and never repeats the redacted body;
capture is idempotent; bad arguments are loud and non-zero.
"""

from __future__ import annotations

import hashlib
import os

from conftest import write_project_config

from refdes import cli as cli_mod
from refdes import history

LOG_SCHEMA = """\
site: { title: History Commands, out: site_out_h4 }
id: { width: 3, ledger: .refdes/ids.yaml }
types:
  log:
    prefix: LOG
    append_only: true
    fields:
      summary: { type: text, required: true }
"""

SECRET = "gallium arsenide"

TWO_LOGS = (
    "defaults: { type: log }\n"
    "items:\n"
    f"  - id: LOG-001\n    summary: Secret note on {SECRET}.\n"
    "  - id: LOG-002\n    summary: Second note.\n"
)

# Same summary on both items: the semantic digests collide, so the two
# captures share one content-addressed object -- the shared-object case.
TWIN_LOGS = (
    "defaults: { type: log, summary: Shared state. }\n"
    "items:\n"
    "  - id: LOG-001\n"
    "  - id: LOG-002\n"
)


def _setup(tmp_path, items_yaml=TWO_LOGS):
    write_project_config(tmp_path, LOG_SCHEMA)
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


def _changes(before, root):
    after = _tree(root)
    return {p for p in set(before) | set(after) if before.get(p) != after.get(p)}


def _warm(tmp_path, capsys, command="check"):
    """One writable run so every incidental write (keys, schema.json) is
    already on disk: from here, a command's own writes are the only diff."""
    config = str(tmp_path / "refdes-project.yaml")
    assert cli_mod.main(["-c", config, command]) == 0
    capsys.readouterr()
    return config


# ------------------------------------------------------------------ capture


def test_capture_writes_exactly_one_object_and_one_event(tmp_path, capsys):
    config = _setup(tmp_path)
    config = _warm(tmp_path, capsys)
    before = _tree(tmp_path)

    assert cli_mod.main(["-c", config, "history", "capture", "LOG-001"]) == 0
    out = capsys.readouterr().out
    assert "captured LOG-001" in out

    changed = _changes(before, tmp_path)
    assert len(changed) == 2, f"capture wrote more than its object+event: {changed}"
    objects = [p for p in changed if p.startswith(".refdes/history/objects/")]
    events = [p for p in changed if p.startswith(".refdes/history/events/")]
    assert len(objects) == 1 and len(events) == 1

    store_events = history.load_events(str(tmp_path))
    assert len(store_events) == 1
    event = store_events[0]
    assert event["kind"] == "captured"
    assert event["item_key"]
    assert event.get("occurred_at"), "an explicit capture carries a clock"
    assert objects[0] == f".refdes/history/objects/{event['object']}.yaml"
    snapshot = history.load_object(str(tmp_path), event["object"])
    assert snapshot["id"] == "LOG-001"
    assert SECRET in snapshot["fields"]["summary"]


def test_capture_is_idempotent(tmp_path, capsys):
    config = _setup(tmp_path)
    config = _warm(tmp_path, capsys)
    assert cli_mod.main(["-c", config, "history", "capture", "LOG-001"]) == 0
    capsys.readouterr()
    before = _tree(tmp_path)

    assert cli_mod.main(["-c", config, "history", "capture", "LOG-001"]) == 0
    out = capsys.readouterr().out
    assert _changes(before, tmp_path) == set()
    assert "already captured" in out
    assert "captured LOG-001: manual capture" not in out  # Q4: no line on a no-op
    assert len(history.load_events(str(tmp_path))) == 1


def test_capture_under_no_write_refuses_and_writes_nothing(tmp_path, capsys):
    config = _setup(tmp_path)
    config = _warm(tmp_path, capsys)
    before = _tree(tmp_path)

    status = cli_mod.main(
        ["-c", config, "--no-write", "history", "capture", "LOG-001"]
    )
    err = capsys.readouterr().err
    assert status == 2
    assert "refusing" in err
    assert _changes(before, tmp_path) == set()
    assert not (tmp_path / ".refdes" / "history").exists()


def test_capture_unknown_item_is_loud(tmp_path, capsys):
    config = _setup(tmp_path)
    config = _warm(tmp_path, capsys)
    before = _tree(tmp_path)

    status = cli_mod.main(["-c", config, "history", "capture", "NOPE-001"])
    err = capsys.readouterr().err
    assert status != 0
    assert "no item" in err and "NOPE-001" in err
    assert _changes(before, tmp_path) == set()


def test_manual_capture_then_edit_warns_edited_after_captured(tmp_path, capsys):
    """The `captured` kind joins the H3 comparison: a manual capture is a
    capture, and editing after it is the same diagnostic, never a failure."""
    config = _setup(tmp_path)
    config = _warm(tmp_path, capsys)
    assert cli_mod.main(["-c", config, "history", "capture", "LOG-001"]) == 0
    capsys.readouterr()

    log = tmp_path / "items" / "log.yaml"
    log.write_text(
        log.read_text(encoding="utf-8").replace(
            f"summary: Secret note on {SECRET}.",
            "summary: Edited after capture.",
        ),
        encoding="utf-8",
    )
    assert cli_mod.main(["-c", config, "check"]) == 0
    out = capsys.readouterr().out
    assert "edited after captured" in out


# ------------------------------------------------------------------- redact


def test_redact_without_confirm_refuses(tmp_path, capsys):
    config = _setup(tmp_path)
    config = _warm(tmp_path, capsys)
    assert cli_mod.main(["-c", config, "history", "capture", "LOG-001"]) == 0
    capsys.readouterr()
    before = _tree(tmp_path)

    status = cli_mod.main(["-c", config, "history", "redact", "LOG-001"])
    err = capsys.readouterr().err
    assert status == 2
    assert "--confirm" in err
    assert _changes(before, tmp_path) == set()


def test_redact_removes_exactly_the_named_content(tmp_path, capsys):
    config = _setup(tmp_path)
    config = _warm(tmp_path, capsys)
    assert cli_mod.main(["-c", config, "history", "capture", "LOG-001"]) == 0
    capsys.readouterr()
    event_before = history.load_events(str(tmp_path))[0]
    object_file = tmp_path / ".refdes" / "history" / "objects" / f"{event_before['object']}.yaml"
    event_file = tmp_path / ".refdes" / "history" / "events" / f"{event_before['id']}.yaml"
    assert object_file.is_file() and event_file.is_file()

    assert cli_mod.main(
        ["-c", config, "history", "redact", "LOG-001", "--confirm"]
    ) == 0
    out = capsys.readouterr().out

    assert "redacted 1 object(s) and 1 event(s)" in out
    # The plan asserts the warning by substring: Git, clones, published.
    assert "Git" in out and "clones" in out and "published" in out

    assert not object_file.exists()
    assert not event_file.exists()

    events = history.load_events(str(tmp_path))  # store still loads
    assert len(events) == 1
    redaction = events[0]
    assert redaction["kind"] == "redaction"
    assert "object" not in redaction  # names removals by digest, holds no snapshot
    assert redaction["item_key"] == event_before["item_key"]
    assert event_before["id"] in redaction["reason"]
    assert event_before["object"] in redaction["reason"]
    # id == filename, per the store's invariant.
    on_disk = list((tmp_path / ".refdes" / "history" / "events").glob("*.yaml"))
    assert [p.name for p in on_disk] == [f"{redaction['id']}.yaml"]


def test_redact_never_repeats_the_redacted_content(tmp_path, capsys):
    """The sabotage test that keeps the audit event from becoming a leak."""
    config = _setup(tmp_path)
    config = _warm(tmp_path, capsys)
    assert cli_mod.main(["-c", config, "history", "capture", "LOG-001"]) == 0
    capsys.readouterr()

    assert cli_mod.main(
        ["-c", config, "history", "redact", "LOG-001", "--confirm"]
    ) == 0
    captured = capsys.readouterr()
    assert SECRET not in captured.out + captured.err
    for dirpath, _dirnames, names in os.walk(
        str(tmp_path / ".refdes" / "history")
    ):
        for name in names:
            with open(os.path.join(dirpath, name), encoding="utf-8") as fh:
                assert SECRET not in fh.read(), f"{name} leaked the redacted body"


def test_redact_keeps_a_shared_object_until_the_last_event(tmp_path, capsys):
    config = _setup(tmp_path, TWIN_LOGS)
    config = _warm(tmp_path, capsys)
    assert cli_mod.main(["-c", config, "history", "capture", "LOG-001"]) == 0
    assert cli_mod.main(["-c", config, "history", "capture", "LOG-002"]) == 0
    capsys.readouterr()
    events = history.load_events(str(tmp_path))
    assert len(events) == 2
    assert events[0]["object"] == events[1]["object"]  # one shared snapshot
    object_file = (
        tmp_path / ".refdes" / "history" / "objects" / f"{events[0]['object']}.yaml"
    )

    assert cli_mod.main(
        ["-c", config, "history", "redact", "LOG-001", "--confirm"]
    ) == 0
    capsys.readouterr()
    assert object_file.exists(), "an object another event still references survives"
    remaining = history.load_events(str(tmp_path))
    redacted_key = next(
        e["item_key"] for e in remaining if e["kind"] == "redaction"
    )
    survivors = [e for e in remaining if e["kind"] == "captured"]
    assert len(survivors) == 1
    assert survivors[0]["item_key"] != redacted_key

    assert cli_mod.main(
        ["-c", config, "history", "redact", "LOG-002", "--confirm"]
    ) == 0
    capsys.readouterr()
    assert not object_file.exists()


def test_redact_by_object_digest(tmp_path, capsys):
    config = _setup(tmp_path)
    config = _warm(tmp_path, capsys)
    assert cli_mod.main(["-c", config, "history", "capture", "LOG-001"]) == 0
    capsys.readouterr()
    digest = history.load_events(str(tmp_path))[0]["object"]

    assert cli_mod.main(
        ["-c", config, "history", "redact", digest, "--confirm"]
    ) == 0
    capsys.readouterr()
    events = history.load_events(str(tmp_path))
    assert [e["kind"] for e in events] == ["redaction"]
    assert events[0]["item_key"] == digest
    assert not (tmp_path / ".refdes" / "history" / "objects" / f"{digest}.yaml").exists()


def test_redact_nothing_matched_is_quiet_and_writes_nothing(tmp_path, capsys):
    config = _setup(tmp_path)
    config = _warm(tmp_path, capsys)
    before = _tree(tmp_path)

    assert cli_mod.main(
        ["-c", config, "history", "redact", "LOG-002", "--confirm"]
    ) == 0
    out = capsys.readouterr().out
    assert "nothing was redacted" in out
    assert _changes(before, tmp_path) == set()


def test_redaction_events_are_not_redaction_targets(tmp_path, capsys):
    """The audit trail of a redaction survives a second redaction of the
    same target -- otherwise the second leak is indistinguishable from no
    leak."""
    config = _setup(tmp_path)
    config = _warm(tmp_path, capsys)
    assert cli_mod.main(["-c", config, "history", "capture", "LOG-001"]) == 0
    assert cli_mod.main(
        ["-c", config, "history", "redact", "LOG-001", "--confirm"]
    ) == 0
    capsys.readouterr()
    before = _tree(tmp_path)

    assert cli_mod.main(
        ["-c", config, "history", "redact", "LOG-001", "--confirm"]
    ) == 0
    out = capsys.readouterr().out
    assert "nothing was redacted" in out
    assert _changes(before, tmp_path) == set()
    assert [e["kind"] for e in history.load_events(str(tmp_path))] == ["redaction"]


def test_redact_under_no_write_refuses(tmp_path, capsys):
    config = _setup(tmp_path)
    config = _warm(tmp_path, capsys)
    assert cli_mod.main(["-c", config, "history", "capture", "LOG-001"]) == 0
    capsys.readouterr()
    before = _tree(tmp_path)

    status = cli_mod.main(
        ["-c", config, "--no-write", "history", "redact", "LOG-001", "--confirm"]
    )
    err = capsys.readouterr().err
    assert status == 2
    assert "refusing" in err
    assert _changes(before, tmp_path) == set()


def test_redact_unknown_target_is_loud(tmp_path, capsys):
    config = _setup(tmp_path)
    config = _warm(tmp_path, capsys)
    before = _tree(tmp_path)

    status = cli_mod.main(
        ["-c", config, "history", "redact", "NOPE-001", "--confirm"]
    )
    err = capsys.readouterr().err
    assert status != 0
    assert "no item or history object" in err
    assert _changes(before, tmp_path) == set()


# ------------------------------------------------------------ migrate-seals


def _sealed(tmp_path, capsys):
    """A writable `build` seals every append-only entry -- the legacy state
    `migrate-seals` reads."""
    config = _setup(tmp_path)
    config = _warm(tmp_path, capsys, command="build")
    assert (tmp_path / ".refdes" / "log-seal.yaml").is_file()
    return config


def test_migrate_seals_writes_markers_and_leaves_the_seal_file_alone(
    tmp_path, capsys
):
    config = _sealed(tmp_path, capsys)
    seal_file = tmp_path / ".refdes" / "log-seal.yaml"
    seal_bytes = seal_file.read_bytes()
    before = _tree(tmp_path)

    assert cli_mod.main(["-c", config, "history", "migrate-seals"]) == 0
    out = capsys.readouterr().out
    assert "2 legacy-seal marker(s) written" in out

    changed = _changes(before, tmp_path)
    assert changed, "migrate-seals wrote nothing"
    assert all(p.startswith(".refdes/history/") for p in changed), changed

    events = history.load_events(str(tmp_path))
    assert len(events) == 2
    for event in events:
        assert event["kind"] == "legacy-seal"
        assert "object" not in event  # recorded hash only; no snapshot
        assert "original content was not captured" in event["reason"]
        assert "log-seal.yaml" in event["reason"]
    assert seal_file.read_bytes() == seal_bytes


def test_migrate_seals_is_idempotent(tmp_path, capsys):
    config = _sealed(tmp_path, capsys)
    assert cli_mod.main(["-c", config, "history", "migrate-seals"]) == 0
    capsys.readouterr()
    before = _tree(tmp_path)

    assert cli_mod.main(["-c", config, "history", "migrate-seals"]) == 0
    out = capsys.readouterr().out
    assert "already migrated" in out
    assert "0 legacy-seal marker(s) written" in out
    assert _changes(before, tmp_path) == set()


def test_migrate_seals_under_no_write_refuses(tmp_path, capsys):
    config = _sealed(tmp_path, capsys)
    before = _tree(tmp_path)

    status = cli_mod.main(
        ["-c", config, "--no-write", "history", "migrate-seals"]
    )
    err = capsys.readouterr().err
    assert status == 2
    assert "refusing" in err
    assert _changes(before, tmp_path) == set()
    assert not (tmp_path / ".refdes" / "history").exists()


def test_migrate_seals_without_seal_files_says_so(tmp_path, capsys):
    config = _setup(tmp_path)
    config = _warm(tmp_path, capsys)  # `check` never seals
    before = _tree(tmp_path)

    assert cli_mod.main(["-c", config, "history", "migrate-seals"]) == 0
    out = capsys.readouterr().out
    assert "no legacy seal files found" in out
    assert _changes(before, tmp_path) == set()
    assert not (tmp_path / ".refdes" / "history").exists()


def test_capture_current_captures_only_matching_content(tmp_path, capsys):
    config = _sealed(tmp_path, capsys)

    assert cli_mod.main(
        ["-c", config, "history", "migrate-seals", "--capture-current"]
    ) == 0
    out = capsys.readouterr().out
    assert out.count("migrated-current event") == 2

    events = history.load_events(str(tmp_path))
    current = [e for e in events if e["kind"] == "migrated-current"]
    assert len(current) == 2
    for event in current:
        assert event.get("occurred_at"), "migrated-current is clearly dated"
        assert "not seal-time text" in event["reason"]
        # The snapshot it names is real and hashes to its filename.
        snapshot = history.load_object(str(tmp_path), event["object"])
        assert snapshot["key"] == event["item_key"]

    # An edit after migration: the live content no longer matches the
    # recorded hash, so a re-run refuses to dress drift up as migration.
    log = tmp_path / "items" / "log.yaml"
    log.write_text(
        log.read_text(encoding="utf-8").replace(
            f"summary: Secret note on {SECRET}.",
            "summary: Edited after sealing.",
        ),
        encoding="utf-8",
    )
    before = _tree(tmp_path)
    assert cli_mod.main(
        ["-c", config, "history", "migrate-seals", "--capture-current"]
    ) == 0
    out = capsys.readouterr().out
    assert "differs" in out
    assert len(
        [e for e in history.load_events(str(tmp_path)) if e["kind"] == "migrated-current"]
    ) == 2
    assert all(p.startswith(".refdes/history/") for p in _changes(before, tmp_path))
