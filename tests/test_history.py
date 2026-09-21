"""Phase H1: the history store, with no call sites.

Sabotage-style: every test tries to *break* the invariant it names — re-append
and check nothing new was written, tamper with a payload and expect a refusal,
change a `log` field and confirm the two digests do NOT collapse into each
other. A store that silently skips a bad record is the failure mode under test.
"""

from __future__ import annotations

import os

import pytest

from refdes import build as build_mod
from refdes import history, parse
from refdes.schema import load_project

from conftest import write_project_config

HISTORY_SCHEMA = """\
site: {title: "History Test", out: _site}
id: {width: 3, ledger: .refdes/ids.yaml}
history: {default: invalidate}
units: {preferred: []}
types:
  note:
    prefix: NOTE
    label: Note
    fields:
      title: { type: text, required: true, on_change: invalidate }
      owner: { type: text, on_change: log }
    links: {}
    body: { on_change: invalidate }
"""


def _project(root, item_files):
    write_project_config(str(root), HISTORY_SCHEMA)
    items = root / "items"
    items.mkdir(exist_ok=True)
    for name, text in item_files.items():
        (items / name).write_text(text, encoding="utf-8")
    project = load_project(config_path=str(root / "refdes-project.yaml"))
    parse.load_items(project)
    return project


def _item(project, item_id):
    for item in project.local_items:
        if item.id == item_id:
            return item
    raise AssertionError(f"{item_id} not parsed")


@pytest.fixture
def root(tmp_path):
    return tmp_path


# --------------------------------------------------------------- round-trip


def test_round_trip(root):
    project = _project(
        root,
        {
            "a.md": """\
---
id: NOTE-A-001
type: note
title: Hello
owner: jared
---
Body text here.
"""
        },
    )
    item = _item(project, "NOTE-A-001")
    digest, path = history.save_object(root, item)
    loaded = history.load_object(root, digest)
    assert loaded == history.object_payload(item)
    assert os.path.normpath(path) == os.path.normpath(history.object_path(root, digest))
    # The plan: history_format is written and read.
    assert "history_format: 1" in open(path, encoding="utf-8").read()
    # Raw link spellings, not resolved ids: nothing resolved is stored.
    assert "resolved" not in loaded


# ------------------------------------------------------- digest stability


def _two_shapes(root):
    """The same note expressed three ways: block YAML, flow YAML with fields
    in a different declaration order, and inherited from a defaults: block."""
    return _project(
        root,
        {
            "block.yaml": """\
items:
  - id: NOTE-A-001
    type: note
    title: Same
    owner: jared
    body: Hello world
""",
            "flow.yaml": """\
items: [ {id: NOTE-A-002, owner: jared, body: Hello world, type: note, title: Same} ]
""",
            "defaults.yaml": """\
defaults: {type: note, prefix: NOTE, title: Same, owner: jared, body: Hello world}
items:
  - id: NOTE-A-003
  - id: NOTE-A-004
    title: Same
    owner: jared
    body: Hello world
""",
        },
    )


def test_digest_stable_across_shape_order_and_defaults(root):
    project = _two_shapes(root)
    digests = {
        item_id: history.semantic_digest(_item(project, item_id))
        for item_id in ("NOTE-A-001", "NOTE-A-002", "NOTE-A-003", "NOTE-A-004")
    }
    assert len(set(digests.values())) == 1, digests


def test_digest_stable_across_body_whitespace(root):
    project = _project(
        root,
        {
            "a.yaml": """\
items:
  - {id: NOTE-A-001, type: note, title: T, body: "hello   world\\n\\ntrailing   "}
  - {id: NOTE-A-002, type: note, title: T, body: "hello world trailing"}
""",
        },
    )
    assert history.semantic_digest(_item(project, "NOTE-A-001")) == history.semantic_digest(
        _item(project, "NOTE-A-002")
    )


def test_digest_changes_when_a_semantic_field_changes(root):
    project = _project(
        root,
        {
            "a.yaml": """\
items:
  - {id: NOTE-A-001, type: note, title: Same, body: b}
  - {id: NOTE-A-002, type: note, title: Different, body: b}
""",
        },
    )
    assert history.semantic_digest(_item(project, "NOTE-A-001")) != history.semantic_digest(
        _item(project, "NOTE-A-002")
    )


def test_log_field_sabotage_digest_moves_content_hash_does_not(root):
    """The test that keeps semantic_digest and content_hash from collapsing
    into each other later: a field marked `on_change: log` is invisible to
    content_hash (a task tick must not churn a baseline) but MUST be visible
    in history."""
    files = {
        "a.md": """\
---
id: NOTE-A-001
type: note
title: T
owner: before
---
Body.
"""
    }
    project = _project(root, files)
    build_mod.build(project)
    before = _item(project, "NOTE-A-001")
    content_hash_before = before.content_hash
    digest_before = history.semantic_digest(before)
    assert content_hash_before  # build actually hashed it

    (root / "items" / "a.md").write_text(
        files["a.md"].replace("owner: before", "owner: after"), encoding="utf-8"
    )
    project2 = _project(root, {})
    build_mod.build(project2)
    after = _item(project2, "NOTE-A-001")
    assert after.content_hash == content_hash_before, "log field must not move content_hash"
    assert history.semantic_digest(after) != digest_before, "log field must move the history digest"


def test_digest_independent_of_hash_format(root, monkeypatch):
    project = _project(
        root,
        {"a.yaml": "items:\n  - {id: NOTE-A-001, type: note, title: T, body: b}\n"},
    )
    item = _item(project, "NOTE-A-001")
    before = history.semantic_digest(item)
    monkeypatch.setattr(build_mod, "HASH_FORMAT", 99)
    assert history.semantic_digest(item) == before, (
        "a HASH_FORMAT bump must never make an item look edited in history"
    )


# ------------------------------------------------------------ object store


def test_save_object_is_content_addressed_and_idempotent(root):
    project = _two_shapes(root)
    a = _item(project, "NOTE-A-001")
    b = _item(project, "NOTE-A-002")
    digest_a, path_a = history.save_object(root, a)
    objects = os.listdir(history.objects_dir(root))
    assert objects == [f"{digest_a}.yaml"]
    digest_b, path_b = history.save_object(root, b)
    assert digest_b == digest_a
    assert os.listdir(history.objects_dir(root)) == objects, "second save wrote a new file"
    # Byte-identical: the file's bytes did not change on re-save.
    assert open(path_a, "rb").read() == open(path_b, "rb").read()


def test_unknown_history_format_refuses(root):
    project = _project(
        root, {"a.yaml": "items:\n  - {id: NOTE-A-001, type: note, title: T, body: b}\n"}
    )
    digest, path = history.save_object(root, _item(project, "NOTE-A-001"))
    text = open(path, encoding="utf-8").read()

    (root / "future.yaml").write_text(
        text.replace("history_format: 1", "history_format: 2"), encoding="utf-8"
    )
    # An unknown higher version refuses rather than guessing.
    with pytest.raises(history.HistoryError, match="newer than this build"):
        history._check_format(
            parse.yaml_safe_load(open(root / "future.yaml", encoding="utf-8")), "future"
        )
    with pytest.raises(history.HistoryError, match="missing history_format"):
        history._check_format({"type": "note"}, "no-format")


def test_tampered_object_is_a_loud_error(root):
    project = _project(
        root, {"a.yaml": "items:\n  - {id: NOTE-A-001, type: note, title: T, body: b}\n"}
    )
    digest, path = history.save_object(root, _item(project, "NOTE-A-001"))
    text = open(path, encoding="utf-8").read()
    # Sabotage the payload in place; the content address must catch it.
    open(path, "w", encoding="utf-8").write(text.replace("title: T", "title: TAMPERED"))
    with pytest.raises(history.HistoryError, match="tampered"):
        history.load_object(root, digest)


def test_save_object_refuses_conflicting_core(root):
    project = _project(
        root, {"a.yaml": "items:\n  - {id: NOTE-A-001, type: note, title: T, body: b}\n"}
    )
    item = _item(project, "NOTE-A-001")
    digest, path = history.save_object(root, item)
    # Sabotage the semantic core under a filename that promises the old one:
    # re-saving must refuse rather than launder the tampered object.
    with open(path, encoding="utf-8") as fh:
        text = fh.read()
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text.replace("title: T", "title: TAMPERED"))
    with pytest.raises(history.HistoryError, match="does not hash to the content address"):
        history.save_object(root, item)


def test_same_state_from_different_files_shares_one_object(root):
    """source is provenance, not content: two items in identical semantic
    state captured from different files land on one object, and the first
    capture's provenance stands."""
    project = _two_shapes(root)
    digest_a, path_a = history.save_object(root, _item(project, "NOTE-A-001"))
    digest_c, path_c = history.save_object(root, _item(project, "NOTE-A-003"))
    assert digest_a == digest_c and path_a == path_c
    loaded = history.load_object(root, digest_a)
    assert loaded["source"]["file"] == "items/block.yaml"


# ------------------------------------------------------------ event records


def test_event_id_is_derived_and_stable():
    a = history.event_id("followed", "KEYPRED", "KEYSUCC")
    b = history.event_id("followed", "KEYPRED", "KEYSUCC")
    assert a == b, "derived ids must be reproducible across calls/processes"
    assert a != history.event_id("followed", "KEYPRED", "OTHER")
    assert a != history.event_id("revision", "KEYPRED", "KEYSUCC")
    assert a != history.event_id("followed", "OTHER", "KEYSUCC")


def test_idempotent_reappend_writes_nothing_new(root):
    path1 = history.append_event(
        root, "followed", "KEYPRED", "d" * 64, successor_key="KEYSUCC", occurred_at="t0"
    )
    events_dir = history.events_dir(root)
    listing = os.listdir(events_dir)
    bytes1 = open(path1, "rb").read()

    # Same edge, later replay clock: must be a filesystem no-op.
    path2 = history.append_event(
        root, "followed", "KEYPRED", "d" * 64, successor_key="KEYSUCC", occurred_at="t1"
    )
    assert path2 == path1
    assert os.listdir(events_dir) == listing, "replay wrote a new file"
    assert open(path1, "rb").read() == bytes1, "replay rewrote the event"

    # Even an append that omits occurred_at entirely is the same edge.
    path3 = history.append_event(root, "followed", "KEYPRED", "d" * 64, successor_key="KEYSUCC")
    assert path3 == path1
    assert open(path1, "rb").read() == bytes1


def test_replay_carrying_a_different_snapshot_is_loud(root):
    history.append_event(root, "followed", "KEYPRED", "a" * 64, successor_key="KEYSUCC")
    with pytest.raises(history.HistoryError, match="already captured"):
        history.append_event(root, "followed", "KEYPRED", "b" * 64, successor_key="KEYSUCC")


def test_unknown_kind_refused(root):
    with pytest.raises(history.HistoryError, match="unknown history event kind"):
        history.append_event(root, "teleported", "KEYPRED", "a" * 64)


def _write_event(root, eid, payload):
    os.makedirs(history.events_dir(root), exist_ok=True)
    path = os.path.join(history.events_dir(root), f"{eid}.yaml")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(history._format_yaml(payload, history._EVENT_HEADER))
    return path


def test_load_malformed_event_is_loud_not_skipped(root):
    good = history.event_id("followed", "K1", "S1")
    history.append_event(root, "followed", "K1", "a" * 64, successor_key="S1")
    assert len(history.load_events(root)) == 1

    # Missing a required key.
    _write_event(
        root,
        "hand-rolled-1",
        {"history_format": 1, "id": "hand-rolled-1", "kind": "followed"},
    )
    with pytest.raises(history.HistoryError, match="missing required key"):
        history.load_events(root)
    os.remove(os.path.join(history.events_dir(root), "hand-rolled-1.yaml"))

    # Unknown kind.
    _write_event(
        root,
        "hand-rolled-2",
        {"history_format": 1, "id": "hand-rolled-2", "kind": "teleported", "item_key": "K", "object": "x"},
    )
    with pytest.raises(history.HistoryError, match="unknown event kind"):
        history.load_events(root)
    os.remove(os.path.join(history.events_dir(root), "hand-rolled-2.yaml"))

    # Id that disagrees with its filename.
    _write_event(
        root,
        "hand-rolled-3",
        {"history_format": 1, "id": "somewhere-else", "kind": "captured", "item_key": "K", "object": "x"},
    )
    with pytest.raises(history.HistoryError, match="does not match its filename"):
        history.load_events(root)
    os.remove(os.path.join(history.events_dir(root), "hand-rolled-3.yaml"))

    # A future history_format refuses rather than guessing.
    _write_event(
        root,
        "hand-rolled-4",
        {"history_format": 99, "id": "hand-rolled-4", "kind": "captured", "item_key": "K", "object": "x"},
    )
    with pytest.raises(history.HistoryError, match="newer than this build"):
        history.load_events(root)
    os.remove(os.path.join(history.events_dir(root), "hand-rolled-4.yaml"))

    assert [e["id"] for e in history.load_events(root)] == [good]


def test_duplicate_edge_under_two_ids_is_loud(root):
    """Only possible if ids were ever random (the doc's original sketch): the
    same (kind, item_key, successor_key) fact recorded twice. The derived-id
    scheme makes this unrepresentable; load enforces it anyway."""
    history.append_event(root, "followed", "K1", "a" * 64, successor_key="S1")
    _write_event(
        root,
        "random-uuid-looking-id",
        {
            "history_format": 1,
            "id": "random-uuid-looking-id",
            "kind": "followed",
            "item_key": "K1",
            "successor_key": "S1",
            "object": "a" * 64,
        },
    )
    with pytest.raises(history.HistoryError, match="duplicate event"):
        history.load_events(root)


def test_load_events_empty_and_sorted(root):
    assert history.load_events(root) == []  # no store at all is not an error
    e2 = history.append_event(root, "captured", "K2", "b" * 64)
    e1 = history.append_event(root, "captured", "K1", "a" * 64)
    ids = [e["id"] for e in history.load_events(root)]
    assert ids == sorted([os.path.basename(e1)[: -len(".yaml")], os.path.basename(e2)[: -len(".yaml")]])


def test_store_directory_is_not_created_without_a_write(root):
    # H1 writes nothing until asked: an untouched project has no history dir.
    _project(root, {"a.yaml": "items:\n  - {id: NOTE-A-001, type: note, title: T, body: b}\n"})
    build_mod.build(load_project(config_path=str(root / "refdes-project.yaml")))
    assert not os.path.exists(history.HISTORY_DIR)
    assert not (root / ".refdes" / "history").exists()
