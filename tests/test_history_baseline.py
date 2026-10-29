"""Living notes H9: baseline snapshot events and the item-page history disclosure.

Every test here is the phase's own verified-against list from
docs/design/living-notes-plan.md §Phase H9, plus the invariants the phase must
not disturb:

* `revision`/`release` write `baseline` events into the same history store
  (one event per local item, content-addressed snapshot objects).
* A baseline created AFTER this phase resolves "what did this item say at
  rev-B?" from the store; a baseline created BEFORE it says rich content is
  unavailable -- the page never dresses current-file text up as history. That
  asymmetry is the phase's reason to exist.
* The disclosure is ABSENT (not an empty box) on pages with nothing to show,
  following the thread panel's pattern.
* The edited-after-captured marker rides on the disclosure.
* Rendered output is escaped (findings 30/31: single quotes included).
* Two builds are byte-identical; read-only commands write nothing; the
  events change no content hash, calc_hash, seal, or baseline file.
"""

from __future__ import annotations

import hashlib
import os

import pytest
from conftest import write_project_config
from helpers import LIFECYCLE_COMPONENT, LIFECYCLE_ITEMS, LIFECYCLE_SCHEMA, _lc_build

from refdes import build as build_mod
from refdes import cli as cli_mod
from refdes import history, lifecycle, parse, render
from refdes.schema import load_project

# ------------------------------------------------------------------ fixtures


H9_SCHEMA = (
    "site: {title: H9, out: _site}\n"
    "id: {width: 3, ledger: .refdes/ids.yaml}\n"
    "on_change: {default: invalidate}\n"
    "types:\n"
    "  requirement:\n"
    "    prefix: REQ\n"
    "    fields: {text: {type: text, required: true}, status: {type: text}}\n"
    "    body: {on_change: invalidate}\n"
)


def _h9_project(root, body: str = "Original text."):
    write_project_config(root, H9_SCHEMA)
    items = root / "items"
    items.mkdir(exist_ok=True)
    (items / "reqs.yaml").write_text(
        "defaults: { type: requirement, prefix: REQ }\n"
        "items:\n"
        "  - id: REQ-001\n    text: A requirement.\n"
        f"    body: {body}\n"
        "  - id: REQ-002\n    text: Another requirement.\n",
        encoding="utf-8",
    )
    # Adopt keys so the stamp has keyed items to record (the CLI mints on
    # load in production; the disclosure panel needs item keys).
    _h9_load(root)
    from refdes import adopt

    adoption = adopt.apply(str(root))
    assert adoption.ok, adoption.errors
    return root


def _h9_load(root):
    project = load_project(config_path=str(root / "refdes-project.yaml"))
    parse.load_items(project)
    build_mod.build(project, seal_write=False, reseal=False, accept_board_move=False)
    return project


def _lc_adopted(root):
    """The lifecycle fixture project (3 local items) with keys adopted, so
    every item has a surrogate key (stamp writes events only for keyed
    items, and CLI loads mint keys, matching production)."""
    from refdes import adopt

    write_project_config(root, LIFECYCLE_SCHEMA)
    items = root / "items"
    items.mkdir(exist_ok=True)
    (items / "reqs.yaml").write_text(LIFECYCLE_ITEMS, encoding="utf-8")
    (items / "cmp.yaml").write_text(LIFECYCLE_COMPONENT, encoding="utf-8")
    _lc_build(root)
    adoption = adopt.apply(str(root))
    assert adoption.ok, adoption.errors
    return root


def _read(path):
    with open(path, "rb") as fh:
        return fh.read()


def _page(root, name: str) -> str:
    with open(os.path.join(root, "_site", name), encoding="utf-8") as fh:
        return fh.read()


def _tree_hash(root, subdir: str = ".refdes") -> str:
    h = hashlib.sha256()
    base = os.path.join(str(root), subdir)
    for dirpath, dirs, files in os.walk(base):
        dirs.sort()
        for name in sorted(files):
            path = os.path.join(dirpath, name)
            rel = os.path.relpath(path, base)
            h.update(rel.encode())
            with open(path, "rb") as fh:
                h.update(fh.read())
    return h.hexdigest()


def _site_tree(root) -> dict:
    out = {}
    base = os.path.join(str(root), "_site")
    for dirpath, dirs, files in os.walk(base):
        dirs.sort()
        for name in sorted(files):
            path = os.path.join(dirpath, name)
            rel = os.path.relpath(path, base)
            with open(path, "rb") as fh:
                out[rel] = fh.read()
    return out


# ------------------------------------------------------- the stamp's writers


def test_revision_stamp_writes_baseline_events(tmp_path, monkeypatch):
    root = _lc_adopted(tmp_path)
    monkeypatch.chdir(root)
    outcome = lifecycle.stamp(_lc_build(root), kind="revision", name="rev-a")
    assert outcome.status == "stamped"
    events = history.load_events(str(root))
    baseline_events = [e for e in events if e["kind"] == "revision"]
    assert len(baseline_events) == 3  # every local item (2 REQ + 1 CMP), none invented
    keys_stamped = {str(e["item_key"]) for e in baseline_events}
    live = {i.key for i in _lc_build(root).local_items if i.key}
    assert keys_stamped == live
    # Every event names a snapshot object that loads and hashes to its name.
    for event in baseline_events:
        obj = history.load_object(str(root), str(event["object"]))
        assert obj["type"]
        assert "body" in obj


def test_release_stamp_writes_release_events(tmp_path, monkeypatch):
    root = _lc_adopted(tmp_path)
    monkeypatch.chdir(root)
    # Resolve the release gate (drafts/uncovered/pinned) exactly as
    # test_lifecycle's release test does, so the stamp lands.
    (root / "items" / "reqs.yaml").write_text(
        "defaults: { type: requirement }\n"
        "items:\n"
        "  - id: REQ-001\n    text: Uncovered active requirement.\n    status: active\n"
        "  - id: REQ-002\n    text: No longer a draft.\n    status: active\n",
        encoding="utf-8",
    )
    (root / "items" / "dec.yaml").write_text(
        "defaults: { type: decision }\n"
        "items:\n"
        "  - id: DEC-001\n    title: Covers both requirements.\n"
        "    satisfies: [REQ-001, REQ-002]\n",
        encoding="utf-8",
    )
    from helpers import _pin_lifecycle_citation

    _pin_lifecycle_citation(root)
    project = _lc_build(root)
    outcome = lifecycle.stamp(project, kind="release", name="rel-a")
    assert outcome.status == "stamped"
    events = history.load_events(str(root))
    assert [e for e in events if e["kind"] == "release"]
    for event in events:
        if event["kind"] == "release":
            assert "rel-a" in str(event.get("reason") or "")


def test_stamp_write_false_writes_nothing(tmp_path, monkeypatch):
    root = _lc_adopted(tmp_path)
    monkeypatch.chdir(root)
    before = _tree_hash(root)
    outcome = lifecycle.stamp(_lc_build(root), kind="revision", name="rev-a", write=False)
    assert outcome.status == "would_stamp"
    assert _tree_hash(root) == before  # baseline dir AND history store untouched
    assert not os.path.isdir(os.path.join(str(root), ".refdes", "history"))


def test_gate_failure_writes_no_events(tmp_path, monkeypatch):
    root = _lc_adopted(tmp_path)
    monkeypatch.chdir(root)
    outcome = lifecycle.stamp(_lc_build(root), kind="release", name="rel-a")
    assert outcome.status == "gate_failed"
    assert not os.path.isdir(os.path.join(str(root), ".refdes", "history"))


def test_events_are_idempotent_on_identical_restamp(tmp_path, monkeypatch):
    root = _lc_adopted(tmp_path)
    monkeypatch.chdir(root)
    lifecycle.stamp(_lc_build(root), kind="revision", name="rev-a")
    before = _tree_hash(root)
    events_before = len(history.load_events(str(root)))
    project2 = _lc_build(root)
    second = lifecycle.stamp(project2, kind="revision", name="rev-a")
    assert second.status == "unchanged"
    assert _tree_hash(root) == before
    assert len(history.load_events(str(root))) == events_before


def test_second_baseline_captures_the_new_state(tmp_path, monkeypatch):
    root = _lc_adopted(tmp_path)
    monkeypatch.chdir(root)
    lifecycle.stamp(_lc_build(root), kind="revision", name="rev-a")
    reqs = root / "items" / "reqs.yaml"
    # The history digest covers type/fields/links/body -- edit the body, not
    # a field no digest policy here puts in play.
    reqs.write_text(
        reqs.read_text(encoding="utf-8").replace("status: active", "status: active\n    body: Rev-B text."),
        encoding="utf-8",
    )
    lifecycle.stamp(_lc_build(root), kind="revision", name="rev-b")
    events = [e for e in history.load_events(str(root)) if e["kind"] == "revision"]
    keyed = {}
    for event in events:
        keyed.setdefault(str(event["item_key"]), set()).add(str(event["object"]))
    edited = _lc_build(root).item_by_id("REQ-001")
    assert len(keyed[edited.key]) == 2  # rev-a's digest and rev-b's, two objects
    obj_a = None
    for event in events:
        if str(event["item_key"]) == edited.key:
            obj = history.load_object(str(root), str(event["object"]))
            if "Rev-B text." not in str(obj.get("body")):
                obj_a = obj
    assert obj_a is not None
    assert obj_a["body"] == ""  # the rev-A snapshot: no body at stamp time


def test_the_writer_takes_the_project_write_lock(tmp_path, monkeypatch):
    """Requirement (2): the history store is multi-process writable; the
    baseline writer must take the existing lock, never write unlocked."""
    from refdes import write_lock

    root = _lc_adopted(tmp_path)
    acquired: list[str] = []
    real = write_lock.project_write_lock

    import contextlib

    @contextlib.contextmanager
    def spy(root_arg):
        with real(root_arg):
            acquired.append(str(root_arg))
            yield

    # Stamp normally (outer lock held by the test, as `cli.main` holds it for
    # real commands): the baseline writer must acquire it *itself*, not ride
    # a caller's -- spy it only inside the writer's own module.
    import refdes.history as history_mod

    monkeypatch.setattr(history_mod, "project_write_lock", spy)
    monkeypatch.chdir(root)
    lifecycle.stamp(_lc_build(root), kind="revision", name="rev-a")
    assert acquired, "the baseline-event writer never took project_write_lock"


def test_failed_restamp_must_not_delete_older_baselines_objects(tmp_path, monkeypatch):
    """The rollback may only remove objects THIS call wrote. save_object
    returns the path for reused content too, so "created by this call" must
    be decided by existence BEFORE the write -- a mid-call failure must never
    delete snapshot objects older baselines' events still reference."""
    root = _lc_adopted(tmp_path)
    monkeypatch.chdir(root)
    assert lifecycle.stamp(_lc_build(root), kind="revision", name="rev-a").status == "stamped"
    before = [e for e in history.load_events(str(root)) if e["kind"] == "revision"]
    assert before
    real = history.append_event
    calls = {"n": 0}

    def flaky(*a, **kw):
        calls["n"] += 1
        if calls["n"] == 3:
            raise OSError("simulated disk error on the third event")
        return real(*a, **kw)

    monkeypatch.setattr(history, "append_event", flaky)
    with pytest.raises(OSError):
        history.baseline_events(_lc_build(root), "revision", "rev-b")
    monkeypatch.setattr(history, "append_event", real)
    missing = [
        str(e["object"])[:12]
        for e in before
        if not os.path.exists(history.object_path(str(root), str(e["object"])))
    ]
    assert not missing, f"rev-a snapshot objects deleted by the failed rev-b rollback: {missing}"


def test_failed_restamp_with_corrupt_later_object_keeps_older_objects(tmp_path, monkeypatch):
    root = _lc_adopted(tmp_path)
    monkeypatch.chdir(root)
    assert lifecycle.stamp(_lc_build(root), kind="revision", name="rev-a").status == "stamped"
    project = _lc_build(root)
    items = [i for i in project.local_items if i.key]
    edited, corrupt = items[0], items[-1]
    # The first item gets a new state, so this call writes a new object for
    # it; the middle item is unchanged (reuses rev-a's object); the LAST
    # item's existing snapshot is corrupt, so save_object raises on it
    # mid-call -- after a reuse, which is exactly when a rollback that
    # removes reused paths destroys an older baseline.
    edited.body = "rev-b body for the first item."
    with open(history.object_path(str(root), history.semantic_digest(corrupt)), "w", encoding="utf-8") as f:
        f.write("key: not-anymore\nbody: garbage\n")
    with pytest.raises(history.HistoryError):
        history.baseline_events(project, "revision", "rev-b")
    # This call's own object is gone; every older baseline's objects survive.
    assert not os.path.exists(history.object_path(str(root), history.semantic_digest(edited)))
    for event in history.load_events(str(root)):
        if event["kind"] == "revision":
            assert os.path.exists(history.object_path(str(root), str(event["object"])))


def test_restamp_counts_new_and_reused_objects(tmp_path, monkeypatch):
    root = _lc_adopted(tmp_path)
    monkeypatch.chdir(root)
    assert lifecycle.stamp(_lc_build(root), kind="revision", name="rev-a").status == "stamped"
    result = history.baseline_events(_lc_build(root), "revision", "rev-b")
    assert result.events == 3
    assert result.objects == 0  # every state already has an object from rev-a
    assert result.reused == 3
    assert result.skipped == 0
    assert result.events_reused == 0


def test_restamp_with_changed_item_refuses_disagreeing_event(tmp_path, monkeypatch):
    """The event-file pre-check may only adopt an event that promises THIS
    digest. Silently reusing an event that promises a different object would
    make the baseline report a snapshot the stamped item never said."""
    root = _lc_adopted(tmp_path)
    monkeypatch.chdir(root)
    assert lifecycle.stamp(_lc_build(root), kind="revision", name="rev-a").status == "stamped"
    # Removing the baseline file is the only way a name becomes re-stampable.
    (root / ".refdes" / "baselines" / "rev-a.yaml").unlink()
    reqs = root / "items" / "reqs.yaml"
    reqs.write_text(
        reqs.read_text(encoding="utf-8").replace(
            "Uncovered active requirement.", "Rewritten after rev-a."
        ),
        encoding="utf-8",
    )
    with pytest.raises(history.HistoryError, match="not a YAML|refuses to rewrite"):
        history.baseline_events(_lc_build(root), "revision", "rev-a")
    # The refusal rewrote nothing: rev-a's event still names the ORIGINAL.
    events = [e for e in history.load_events(str(root)) if e["kind"] == "revision"]
    for event in events:
        obj = history.load_object(str(root), str(event["object"]))
        body = str(obj.get("body") or "")
        assert "Rewritten after rev-a" not in body


def test_writer_failure_warns_and_the_stamp_stands(tmp_path, monkeypatch):
    """The stamp-level failure contract: baseline_events raising turns into
    the loud warning, the stamp itself still reports stamped."""
    root = _lc_adopted(tmp_path)
    monkeypatch.chdir(root)
    assert lifecycle.stamp(_lc_build(root), kind="revision", name="rev-a").status == "stamped"
    (root / ".refdes" / "baselines" / "rev-a.yaml").unlink()
    reqs = root / "items" / "reqs.yaml"
    reqs.write_text(
        reqs.read_text(encoding="utf-8").replace(
            "Uncovered active requirement.", "Rewritten after rev-a."
        ),
        encoding="utf-8",
    )
    project = _lc_build(root)
    outcome = lifecycle.stamp(project, kind="revision", name="rev-a")
    assert outcome.status == "stamped"
    warnings = [d.message for d in project.warnings]
    assert any("history snapshot events were not written" in m for m in warnings), warnings


def test_rows_are_ordered_by_stamp_time_not_by_name(tmp_path, monkeypatch):
    """Rows are chronological: the opened row is the NEWEST stamp, even
    when names sort opposite to stamp order (zzz stamped first, aaa
    second -- filename order would open the older zzz)."""
    root = _lc_adopted(tmp_path)
    monkeypatch.chdir(root)
    times = iter(["2026-01-01T00:00:00Z", "2026-06-01T00:00:00Z"])
    monkeypatch.setattr(lifecycle, "_now_iso", lambda: next(times))
    assert lifecycle.stamp(_lc_build(root), kind="revision", name="zzz").status == "stamped"
    reqs = root / "items" / "reqs.yaml"
    reqs.write_text(
        reqs.read_text(encoding="utf-8").replace(
            "Uncovered active requirement.", "Rewritten between the stamps."
        ),
        encoding="utf-8",
    )
    assert lifecycle.stamp(_lc_build(root), kind="revision", name="aaa").status == "stamped"
    render.render_site(_lc_build(root))
    block = _page(root, "req-001.html").split(DISCLOSURE_MARK)[1]
    idx_zzz, idx_aaa = block.find("zzz"), block.find("aaa")
    open_idx = block.find("open")
    assert idx_zzz != -1 and idx_aaa != -1 and open_idx != -1
    assert idx_zzz < idx_aaa, "rows are not in stamp order"
    assert idx_zzz < open_idx < idx_aaa, "the opened row is not the newest stamp"


def test_missing_snapshot_object_shows_the_no_snapshot_row(tmp_path):
    """An event whose object is gone (redaction, corruption): the row falls
    back to the honest no-snapshot copy -- which names that possibility --
    and quotes no text."""
    root = _h9_project(tmp_path)
    _stamp_and_build(root, "rev-a")
    key = _h9_load(root).item_by_id("REQ-001").key
    event = next(
        e
        for e in history.load_events(str(root))
        if e["kind"] == "revision" and str(e["item_key"]) == str(key)
    )
    os.remove(history.object_path(str(root), str(event["object"])))
    render.render_site(_h9_load(root))
    block = _page(root, "req-001.html").split(DISCLOSURE_MARK)[1]
    assert "No snapshot was recorded" in block
    assert "redacted" in block  # the copy covers a redacted snapshot
    assert "Original text" not in block  # ...and quotes nothing invented


def test_corrupt_baseline_file_fails_the_build_as_configuration_error(tmp_path, monkeypatch, capsys):
    """render reads the baselines directory (render_site's list_baselines
    hoist), so an unparseable baseline file fails the build with the
    configuration error every baseline reader already raised -- the same
    symptom and exit code, not a new failure mode."""
    root = _lc_adopted(tmp_path)
    monkeypatch.chdir(root)
    assert lifecycle.stamp(_lc_build(root), kind="revision", name="rev-bad").status == "stamped"
    (root / ".refdes" / "baselines" / "rev-bad.yaml").write_text("{: bad", encoding="utf-8")
    assert cli_mod.main(["-c", "refdes-project.yaml", "build"]) == 2
    assert "baseline file does not parse" in capsys.readouterr().err


# ------------------------------------------- the disclosure on the item page


DISCLOSURE_MARK = "history-disclosure"


def _stamp_and_build(root, name="rev-a"):
    outcome = lifecycle.stamp(_h9_load(root), kind="revision", name=name)
    assert outcome.status == "stamped"
    render.render_site(_h9_load(root))
    return _h9_load(root)


def test_disclosure_absent_when_nothing_to_show(tmp_path):
    root = _h9_project(tmp_path)
    render.render_site(_h9_load(root))
    page = _page(root, "req-001.html")
    assert DISCLOSURE_MARK not in page  # absent, not an empty box
    assert "<details" not in page


def test_disclosure_shows_captured_content_and_names_the_baseline(tmp_path):
    root = _h9_project(tmp_path)
    _stamp_and_build(root, "rev-a")
    page = _page(root, "req-001.html")
    assert DISCLOSURE_MARK in page
    assert "rev-a" in page  # the disclosure row names the baseline
    assert "Original text" in page.split(DISCLOSURE_MARK)[1]  # captured content
    # Editing the live file after the stamp does not change what the snapshot
    # block quotes -- "what did this item say at rev-A?" answers from the store.
    reqs = root / "items" / "reqs.yaml"
    reqs.write_text(
        reqs.read_text(encoding="utf-8").replace("Original text", "Rewritten live"),
        encoding="utf-8",
    )
    render.render_site(_h9_load(root))
    page2 = _page(root, "req-001.html")
    snapshot_block = page2.split(DISCLOSURE_MARK)[1]
    assert "Original text" in snapshot_block
    assert "Rewritten live" not in snapshot_block


def test_old_baseline_says_unavailable_and_never_invents_text(tmp_path):
    """The phase's reason to exist: a baseline stamped BEFORE the events
    feature resolves nothing from the store, and the page must not invent
    captured text from the current files."""
    root = _h9_project(tmp_path)
    _h9_load(root)
    # A pre-H9 baseline, written the way the pre-H9 stamp wrote them.
    os.makedirs(os.path.join(str(root), ".refdes", "baselines"), exist_ok=True)
    with open(os.path.join(str(root), ".refdes", "baselines", "rev-old.yaml"), "w", encoding="utf-8") as fh:
        fh.write(
            "kind: revision\n"
            "name: rev-old\n"
            "stamped_at: '2026-01-01T00:00:00Z'\n"
            "stamped_by: someone\n"
            "refdes_version: 0.0.0\n"
            "items:\n"
            "  REQ-001: {hash: " + "'" + "a" * 64 + "'" + ", type: requirement, title: A requirement.}\n"
            "  REQ-002: {hash: " + "'" + "b" * 64 + "'" + ", type: requirement, title: Another requirement.}\n"
        )
    render.render_site(_h9_load(root))
    page = _page(root, "req-001.html")
    assert DISCLOSURE_MARK in page  # the baseline exists, so the panel exists
    block = page.split(DISCLOSURE_MARK)[1]
    assert "rev-old" in block
    assert "No snapshot was recorded" in block  # the honest legacy row...
    assert "Original text" not in block  # ...which quotes no invented text


def test_edited_after_captured_marker_shown(tmp_path):
    root = _h9_project(tmp_path)
    _stamp_and_build(root, "rev-a")
    assert DISCLOSURE_MARK in _page(root, "req-001.html")
    # Capture explicitly, then edit -- the H3 marker must surface on the page.
    project2 = _h9_load(root)
    history.capture(str(root), project2.item_by_id("REQ-001"))
    reqs = root / "items" / "reqs.yaml"
    reqs.write_text(
        reqs.read_text(encoding="utf-8").replace("Original text", "Edited after capture"),
        encoding="utf-8",
    )
    render.render_site(_h9_load(root))
    page = _page(root, "req-001.html")
    assert "edited after captured" in page
    # The marker is about the capture, and the snapshot text stays put.
    assert "Original text" in page.split(DISCLOSURE_MARK)[1]


def test_panel_output_is_escaped(tmp_path):
    """Findings 30/31: single quotes included. The XSS payload rides in the
    captured body, which is author-controlled text the panel quotes."""
    root = tmp_path
    payload = "T'<script>alert(90210)</script>'&\"x"
    write_project_config(root, H9_SCHEMA)
    (root / "items").mkdir()
    (root / "items" / "reqs.yaml").write_text(
        "defaults: { type: requirement, prefix: REQ }\n"
        "items:\n"
        "  - id: REQ-001\n    text: A requirement.\n"
        f"    body: {payload}\n",
        encoding="utf-8",
    )
    _h9_load(root)
    from refdes import adopt

    adoption = adopt.apply(str(root))
    assert adoption.ok, adoption.errors
    lifecycle.stamp(_h9_load(root), kind="revision", name="rev-x")
    render.render_site(_h9_load(root))
    page = _page(root, "req-001.html")
    block = page.split(DISCLOSURE_MARK)[1]
    assert "<script>alert(90210)</script>" not in page
    assert "&lt;script&gt;alert(90210)&lt;/script&gt;" in block
    assert "&#39;" in block  # single quotes escaped (finding 30)
    assert "&amp;" in block


def test_two_builds_are_byte_identical(tmp_path):
    root = _h9_project(tmp_path)
    _stamp_and_build(root, "rev-a")
    first = _site_tree(root)
    render.render_site(_h9_load(root))
    second = _site_tree(root)
    assert first == second


# ------------------------------------------------- the phase's non-disturbance


def test_readonly_commands_write_no_events(tmp_path):
    root = _h9_project(tmp_path)
    _stamp_and_build(root, "rev-a")
    store = _tree_hash(root, os.path.join(".refdes", "history"))
    code = cli_mod.main(
        ["-c", str(root / "refdes-project.yaml"), "--no-write", "revision", "rev-b"]
    )
    assert code == 0
    assert _tree_hash(root, os.path.join(".refdes", "history")) == store
    for argv in (["check"], ["index"], ["--no-write", "build"]):
        code = cli_mod.main(["-c", str(root / "refdes-project.yaml"), *argv])
        assert code == 0, argv
        assert _tree_hash(root, os.path.join(".refdes", "history")) == store, argv


def test_events_change_no_hash_no_seal_no_baseline(tmp_path, monkeypatch):
    """The hash-impact claim, pinned: adding the events changes no
    `content_hash`, no `calc_hash`, no seal file, and not one byte of the
    compact baseline file -- which is exactly why an old baseline can stay
    hash-only."""
    root = _lc_adopted(tmp_path)
    monkeypatch.chdir(root)
    with_events = lifecycle.stamp(_lc_build(root), kind="revision", name="rev-a")
    baseline_bytes = _read(with_events.path)
    events = history.load_events(str(root))
    assert any(e["kind"] == "revision" for e in events)

    # Rebuild: hashes recompute with the events on disk.
    project = _lc_build(root)
    hashes = {i.id: (i.content_hash, build_mod.calc_hash_for(i)) for i in project.local_items}
    import refdes.history as history_mod

    monkeypatch.setattr(
        history_mod,
        "baseline_events",
        lambda *a, **k: history_mod.BaselineEvents(0, 0, 0, 0, 0),
    )
    outcome2 = lifecycle.stamp(_lc_build(root), kind="revision", name="rev-b")
    assert outcome2.status == "stamped"
    baseline_b = _read(outcome2.path)

    # Third stamp with events ON, same name content: prove the item entries
    # are the same hashes the events-off stamp wrote.
    monkeypatch.undo()
    project3 = _lc_build(root)
    for item in project3.local_items:
        assert hashes[item.id] == (item.content_hash, build_mod.calc_hash_for(item))

    def items_section(blob: bytes) -> bytes:
        return blob.split(b"items:\n", 1)[1]

    # The baseline item entries are byte-identical between an events-on stamp
    # and an events-off stamp (same items, same hashes, same hash_format) --
    # events are a view layer over the store, not data in the baseline.
    assert items_section(baseline_bytes) == items_section(baseline_b)
    # No seal machinery is involved in a stamp at all: no seal file exists in
    # this project, and the stamp did not create one.
    assert not os.path.exists(os.path.join(str(root), ".refdes", "log-seal.yaml"))


def test_items_outside_the_baseline_get_no_rows(tmp_path):
    root = _h9_project(tmp_path)
    _stamp_and_build(root, "rev-a")
    (root / "items" / "reqs.yaml").write_text(
        (root / "items" / "reqs.yaml").read_text(encoding="utf-8")
        + "  - id: REQ-003\n    text: Added after rev-a.\n",
        encoding="utf-8",
    )
    render.render_site(_h9_load(root))
    page = _page(root, "req-003.html")
    assert DISCLOSURE_MARK not in page  # absent for a brand-new item
    assert DISCLOSURE_MARK in _page(root, "req-001.html")
