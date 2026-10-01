"""Lost-key diagnostic and explicit original-identity recovery."""

from __future__ import annotations

import json

import pytest
import yaml
from conftest import write_project_config

from refdes import (
    build,
    cli,
    history,
    key_restore,
    keys,
    lifecycle,
    loader,
    patcher,
    revise,
    seal,
    textio,
)

CONFIG = """\
site: {title: Key recovery, out: _site}
link_types:
  refines: {inverse: refined_by, label: Refines}
types:
  requirement:
    prefix: REQ
    fields:
      title: {type: text, required: true}
    links:
      refines: [requirement]
  bound:
    prefix: BND
    fields:
      limit: {type: limit, required: true}
  decision:
    prefix: DEC
    fields:
      checks: {type: checks}
  log:
    prefix: LOG
    append_only: true
    fields:
      title: {type: text, required: true}
    links:
      refines: [requirement]
"""


def _snapshot(root):
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*") if p.is_file()}


def _fixture(root, shape="md", missing=False):
    config = write_project_config(root, CONFIG)
    (root / "items").mkdir()
    original, current, source_key = keys.mint(), keys.mint(), keys.mint()
    key_line = "" if missing else f"key: '{current}' # preserve comment\n"
    if shape == "md":
        text = f"---\nid: REQ-001\n{key_line}type: requirement\ntitle: Target\n---\nBody.\n"
        path = root / "items/target.md"
    elif shape == "flow":
        text = f"defaults: {{type: requirement}}\nitems:\n  - {{id: REQ-001, key: '{current}', title: Target}}\n"
        path = root / "items/target.yaml"
    else:
        text = "defaults: {type: requirement}\nitems:\n  - id: REQ-001\n"
        text += "" if missing else f"    key: '{current}' # preserve comment\n"
        text += "    title: Target\n  - {id: REQ-003, title: Other}\n"
        path = root / "items/target.yaml"
    path.write_bytes(text.replace("\n", "\r\n").encode())
    (root / "items/source.yaml").write_text(
        "defaults: {type: requirement}\nitems:\n"
        f"  - id: REQ-002\n    key: {source_key}\n    title: Source\n"
        f"    refines: [REQ-001@{original}]\n",
        encoding="utf-8",
    )
    return str(config), path, original, current


def _message(original, current, *, pointer="refines points at", label="REQ-001"):
    declared = f"declares key {current!r}" if current else "declares no key"
    loss = "lost and regenerated" if current else "lost"
    return (
        f"{pointer} key {original!r} (labelled {label}), which no item declares. "
        f"A live item labelled {label} {declared}. Its key may have been {loss}, "
        "or the label may now name a different item. The "
        "label is not used as a fallback. Check git history to confirm identity. "
        f"If it is the same item, run `refdes keys restore {label}@{original} "
        "--dry-run`, then repeat without --dry-run to restore the original key."
    )


def test_exact_lost_key_repro(tmp_path, capsys):
    config = write_project_config(tmp_path, CONFIG)
    (tmp_path / "items").mkdir()
    target = tmp_path / "items/target.md"
    target.write_text("---\nid: REQ-001\ntype: requirement\ntitle: Target\n---\nBody.\n")
    source = tmp_path / "items/source.yaml"
    source.write_text(
        "defaults: {type: requirement}\nitems:\n  - id: REQ-002\n    title: Source\n    refines: [REQ-001]\n"
    )
    args = ["-c", str(config)]
    assert cli.main(args + ["id"]) == 0
    original = loader.load_readonly(str(config)).item_by_id("REQ-001").key
    target.write_text(
        "\n".join(line for line in target.read_text().split("\n") if not line.startswith("key:"))
    )
    assert cli.main(args + ["id"]) == 0
    project = loader.load_readonly(str(config))
    current = project.item_by_id("REQ-001").key
    assert current and current != original
    assert project.errors[0].message == _message(original, current)
    assert project.item_by_id("REQ-002").resolved_links == {}
    assert cli.main(args + ["check"]) == 1
    capsys.readouterr()
    assert cli.main(args + ["keys", "adopt"]) == 1
    assert "project has existing build errors" in capsys.readouterr().err
    before = _snapshot(tmp_path)
    assert cli.main(args + ["keys", "restore", f"REQ-001@{original}", "--dry-run"]) == 0
    assert f"would restore REQ-001: {current} -> {original}" in capsys.readouterr().out
    assert _snapshot(tmp_path) == before
    assert cli.main(args + ["keys", "restore", f"REQ-001@{original}"]) == 0
    assert source.read_bytes() == before["items/source.yaml"]
    assert cli.main(args + ["--no-write", "check"]) == 0
    assert loader.load_readonly(str(config)).item_by_id("REQ-002").resolved_links == {
        "refines": ["REQ-001"]
    }


@pytest.mark.parametrize(
    "shape,missing",
    [("md", False), ("block", False), ("flow", False), ("md", True), ("block", True)],
)
def test_restore_preserves_source_shapes_and_is_idempotent(tmp_path, shape, missing, capsys):
    config, path, original, current = _fixture(tmp_path, shape, missing)
    before = _snapshot(tmp_path)
    args = ["-c", config, "keys", "restore", f"REQ-001@{original}"]
    assert cli.main(["--no-write"] + args) == 0
    assert _snapshot(tmp_path) == before
    assert cli.main(args) == 0
    after = _snapshot(tmp_path)
    assert {p for p in after if before[p] != after[p]} == {path.relative_to(tmp_path).as_posix()}
    if not missing:
        assert path.read_bytes() == before[path.relative_to(tmp_path).as_posix()].replace(
            current.encode(), original.encode()
        )
    else:
        assert b"\n" not in path.read_bytes().replace(b"\r\n", b"")
    assert not loader.load_readonly(config).errors
    assert cli.main(args) == 0
    assert "nothing to do -- original keys already declared" in capsys.readouterr().out
    assert _snapshot(tmp_path) == after


@pytest.mark.parametrize("missing", [False, True])
def test_live_label_and_absent_label_diagnostics(tmp_path, missing):
    config, _path, original, current = _fixture(tmp_path, missing=missing)
    project = loader.load_readonly(config)
    assert project.errors[0].message == _message(original, "" if missing else current)
    for target in (f"REQ-999@{original}", original):
        message = build._unknown_key_message(project, "refines points at", target)
        assert "The target may have been deleted or its key lost or changed." in message
        assert "predates" not in message
        assert "keys restore" not in message


@pytest.mark.parametrize("dry_run", [False, True])
def test_unrelated_error_and_newly_dangling_current_reference_refuse(tmp_path, dry_run):
    config, _path, original, current = _fixture(tmp_path)
    extra = tmp_path / "items/extra.yaml"
    extra.write_text(
        f"defaults: {{type: requirement}}\nitems:\n  - id: REQ-004\n    title: Extra\n    refines: [REQ-001@{current}]\n"
    )
    before = _snapshot(tmp_path)
    result = key_restore.apply(str(tmp_path), [f"REQ-001@{original}"], dry_run=dry_run)
    assert not result.ok
    assert "restored project would still have build errors" in result.errors[0]
    assert _snapshot(tmp_path) == before
    extra.write_text("defaults: {type: requirement}\nitems:\n  - id: REQ-004\n")
    before = _snapshot(tmp_path)
    assert not key_restore.apply(str(tmp_path), [f"REQ-001@{original}"], dry_run=dry_run).ok
    assert _snapshot(tmp_path) == before


def test_duplicate_key_bad_key_and_unknown_item_refuse(tmp_path):
    config, _path, original, _current = _fixture(tmp_path)
    project = loader.load_readonly(config)
    used = project.item_by_id("REQ-002").key
    before = _snapshot(tmp_path)
    for targets in (
        [f"REQ-001@{used}"],
        ["REQ-001@bad"],
        [f"REQ-999@{original}"],
        ["REQ-001"],
        [f"REQ-001@{original}"] * 2,
    ):
        assert not key_restore.apply(str(tmp_path), targets).ok
        assert _snapshot(tmp_path) == before


def test_recorded_replacement_key_cannot_be_discarded_even_in_older_baseline(tmp_path):
    config, _path, original, current = _fixture(tmp_path)
    source = tmp_path / "items/source.yaml"
    original_source = source.read_text()
    source.write_text(original_source.replace(original, current))
    project = loader.load_readonly(config)
    assert not project.errors
    assert lifecycle.stamp(project, kind="revision", name="before").status == "stamped"
    # Stamp a clean, later project where the target was temporarily absent.
    path = tmp_path / "items/target.md"
    project = loader.load_readonly(
        config,
        overlay={
            str(path): "---\nsection: Temporarily absent target\n---\n",
            str(source): original_source.replace(f"    refines: [REQ-001@{original}]\n", ""),
        },
    )
    assert not project.errors
    assert lifecycle.stamp(project, kind="revision", name="after").status == "stamped"
    source.write_text(original_source)
    before = _snapshot(tmp_path)
    result = key_restore.apply(str(tmp_path), [f"REQ-001@{original}"])
    assert not result.ok
    assert "baseline 'before'" in result.errors[0]
    assert _snapshot(tmp_path) == before


@pytest.mark.parametrize("phase", ["write", "validation", "no_write"])
def test_transaction_rolls_back_on_failure(tmp_path, monkeypatch, phase):
    _config, _path, original, _current = _fixture(tmp_path)
    before = _snapshot(tmp_path)
    write = revise.write_rewrites

    def fail(rewrites):
        if phase == "no_write":
            return
        write(rewrites)
        if phase == "write":
            raise OSError("injected failure")
        text = rewrites[0].after.replace("title: Target", "title: null")
        textio.write_text(rewrites[0].path, text)

    monkeypatch.setattr(revise, "write_rewrites", fail)
    result = key_restore.apply(str(tmp_path), [f"REQ-001@{original}"])
    assert not result.ok
    assert "rolled back" in result.errors[0]
    assert _snapshot(tmp_path) == before


def test_generic_field_edit_still_cannot_change_identity():
    text = "---\nid: REQ-001\nkey: abc\ntype: requirement\n---\n"
    assert isinstance(
        patcher.plan_patch(text, "REQ-001", patcher.SetField("key", keys.mint())), patcher.Refusal
    )


def test_multiple_lost_keys_in_one_file_are_restored_together(tmp_path):
    config, _path, original, _current = _fixture(tmp_path)
    second_original, second_current = keys.mint(), keys.mint()
    path = tmp_path / "items/target.md"
    path.write_text(
        path.read_text()
        + f"---\nid: REQ-004\nkey: {second_current}\ntype: requirement\ntitle: Second\n---\nBody.\n"
    )
    source = tmp_path / "items/source.yaml"
    source.write_text(
        source.read_text().replace(
            f"REQ-001@{original}", f"REQ-001@{original}, REQ-004@{second_original}"
        )
    )
    before = _snapshot(tmp_path)
    assert not key_restore.apply(str(tmp_path), [f"REQ-001@{original}"]).ok
    assert _snapshot(tmp_path) == before
    result = key_restore.apply(str(tmp_path), [f"REQ-001@{original}", f"REQ-004@{second_original}"])
    assert result.ok, result.errors
    assert result.changed_files == ["items/target.md"]
    assert not loader.load_readonly(config).errors


@pytest.mark.parametrize("missing", [False, True])
def test_original_history_hashes_and_inbound_seal_survive_restoration(tmp_path, missing):
    config, path, original, current = _fixture(tmp_path)
    textio.write_text(str(path), textio.read_text(str(path)).replace(current, original))
    source = tmp_path / "items/source.yaml"
    source.write_text(
        source.read_text().replace("type: requirement", "type: log").replace("REQ-002", "LOG-002")
    )
    marker = tmp_path / keys.ADOPTION_MARKER
    marker.parent.mkdir(exist_ok=True)
    marker.write_text("adopted: true\nformat: 1\n")
    healthy = loader.load_readonly(config)
    build.build(healthy, seal_write=True)
    hashes = {i.id: i.content_hash for i in healthy.local_items}
    assert lifecycle.stamp(healthy, kind="revision", name="original").status == "stamped"
    text = textio.read_text(str(path)).replace(original, current)
    if missing:
        text = "".join(l for l in text.splitlines(keepends=True) if not l.startswith("key:"))
    textio.write_text(str(path), text)
    before = _snapshot(tmp_path)
    result = key_restore.apply(str(tmp_path), [f"REQ-001@{original}"])
    assert result.ok, result.errors
    restored = loader.load_readonly(config)
    assert not restored.errors
    assert {i.id: i.content_hash for i in restored.local_items} == hashes
    for rel, contents in before.items():
        if rel != "items/target.md":
            assert (tmp_path / rel).read_bytes() == contents


@pytest.mark.parametrize("record_kind", ["seal", "membership", "capture", "successor"])
def test_recorded_current_key_in_seal_or_membership_refuses(tmp_path, record_kind):
    config, _path, original, current = _fixture(tmp_path)
    (tmp_path / ".refdes").mkdir(exist_ok=True)
    if record_kind == "seal":
        (tmp_path / ".refdes/log-seal-retired-board.yaml").write_text(
            seal.format_seals({current: {"id": "REQ-001", "hash": "old"}})
        )
    elif record_kind == "membership":
        (tmp_path / ".refdes/boards.yaml").write_text(
            yaml.safe_dump({"boards": {current: {"id": "REQ-001", "board": ""}}})
        )
    elif record_kind == "capture":
        history.capture(str(tmp_path), loader.load_readonly(config).item_by_id("REQ-001"))
    else:
        history.append_event(str(tmp_path), "followed", original, "a" * 64, successor_key=current)
    before = _snapshot(tmp_path)
    result = key_restore.apply(str(tmp_path), [f"REQ-001@{original}"])
    assert not result.ok
    assert "would orphan that history" in result.errors[0]
    assert _snapshot(tmp_path) == before


@pytest.mark.parametrize("current_value", [5, 15])
def test_shared_diagnostic_and_recovery_for_checks_and_calc_refs(tmp_path, current_value):
    config = write_project_config(tmp_path, CONFIG)
    (tmp_path / "items").mkdir()
    old_bound, new_bound, old_decision, new_decision = [keys.mint() for _ in range(4)]
    (tmp_path / "items/bound.yaml").write_text(
        f"defaults: {{type: bound}}\nitems:\n  - id: BND-001\n    key: {new_bound}\n    limit: '<= 10 A'\n"
    )
    (tmp_path / "items/target.md").write_text(
        f"---\nid: DEC-001\nkey: {new_decision}\ntype: decision\n---\n```calc\nI = {current_value} A\n```\n"
    )
    (tmp_path / "items/check.md").write_text(
        f"---\nid: DEC-002\ntype: decision\nchecks: [{{value: I, against: BND-001@{old_bound}}}]\n---\n```calc\nI = DEC-001@{old_decision}.I\n```\n"
    )
    project = loader.load_readonly(str(config))
    assert any(
        d.message == _message(old_bound, new_bound, pointer="check against", label="BND-001")
        for d in project.errors
    )
    assert any(
        _message(
            old_decision,
            new_decision,
            pointer=f"calc reference 'DEC-001@{old_decision}.I'",
            label="DEC-001",
        )
        in d.message
        for d in project.errors
    )
    result = key_restore.apply(str(tmp_path), [f"BND-001@{old_bound}", f"DEC-001@{old_decision}"])
    assert result.ok, result.errors
    from refdes.model import CHECK_VIOLATION

    remaining = loader.load_readonly(str(config)).errors
    assert len(remaining) == (1 if current_value == 15 else 0)
    assert all(d.code == CHECK_VIOLATION for d in remaining)


def test_imported_key_ownership_and_upstream_diagnostic(tmp_path):
    config, _path, original, current = _fixture(tmp_path)
    artifact = tmp_path / "upstream.json"
    artifact.write_text(
        json.dumps(
            {
                "title": "Upstream",
                "items": [
                    {
                        "id": "REQ-IMP-001",
                        "key": original,
                        "type": "requirement",
                        "fields": {"title": "Imported"},
                        "links": {},
                    }
                ],
            }
        )
    )
    settings = tmp_path / "refdes-project.yaml"
    settings.write_text(
        settings.read_text() + "imports:\n  - name: upstream\n    items: upstream.json\n"
    )
    before = _snapshot(tmp_path)
    result = key_restore.apply(str(tmp_path), [f"REQ-001@{original}"])
    assert not result.ok
    assert "already declared by REQ-IMP-001" in result.errors[0]
    assert _snapshot(tmp_path) == before
    project = loader.load_readonly(config)
    message = build._unknown_key_message(project, "refines points at", f"REQ-IMP-001@{current}")
    assert "restore its original key upstream" in message
    assert "refdes keys restore" not in message
    # F4: the composite is the thing the downstream author did not write, and
    # the message has to say so -- see the end-to-end test below for the same
    # text arriving through the CLI.
    assert "written into your file by refdes on a load, not typed by hand" in message
    assert "see https://squishiba.github.io/refdes/multi-board.html" in message


def test_external_lost_key_diagnostic_names_the_composite_as_tool_written(tmp_path, capsys):
    """F4, end to end: the composite in the downstream file was written by a
    `refdes check`, and the error for it says so.

    An upstream artifact carrying a key, a downstream `refines` written bare by
    its author, one ordinary writable load expanding it into their own file,
    then the upstream key regenerated. The diagnostic the author is left with
    has to name the composite as a refdes artifact and point at the import
    docs, while a *local* lost key keeps the `keys restore` recipe instead.
    """
    config = write_project_config(tmp_path, CONFIG)
    (tmp_path / "items").mkdir()
    original, regenerated = keys.mint(), keys.mint()
    artifact = tmp_path / "upstream.json"

    def write_artifact(key: str) -> None:
        artifact.write_text(
            json.dumps(
                {
                    "title": "Upstream",
                    "items": [
                        {
                            "id": "REQ-IMP-001",
                            "key": key,
                            "type": "requirement",
                            "fields": {"title": "Imported"},
                            "links": {},
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )

    write_artifact(original)
    settings = tmp_path / "refdes-project.yaml"
    settings.write_text(
        settings.read_text() + "imports:\n  - name: upstream\n    items: upstream.json\n",
        encoding="utf-8",
    )
    source = tmp_path / "items/source.yaml"
    source.write_text(
        "defaults: {type: requirement}\nitems:\n"
        "  - id: REQ-002\n    title: Source\n    refines: [REQ-IMP-001]\n",
        encoding="utf-8",
    )

    # A plain `refdes check` -- no write asked for -- expands the bare target
    # against the imported item's key, in the downstream author's own file.
    assert cli.main(["-c", str(config), "check"]) == 0
    assert f"REQ-IMP-001@{original}" in source.read_text()

    write_artifact(regenerated)
    capsys.readouterr()
    assert cli.main(["-c", str(config), "check"]) == 1
    captured = capsys.readouterr()
    reported = captured.out + captured.err
    assert f"key {original!r} (labelled REQ-IMP-001), which no item declares" in reported
    assert "written into your file by refdes on a load, not typed by hand" in reported
    assert "see https://squishiba.github.io/refdes/multi-board.html" in reported
    assert "refdes keys restore" not in reported

    # The local branch keeps its own ending and stays free of the import clause.
    project = loader.load_readonly(str(config))
    local = build._unknown_key_message(project, "refines points at", f"REQ-002@{keys.mint()}")
    assert "refdes keys restore REQ-002@" in local
    assert "multi-board.html" not in local


def test_intervening_source_edit_is_preserved(tmp_path, monkeypatch):
    config, path, original, _current = _fixture(tmp_path)
    load = loader.load_readonly
    concurrent = textio.read_text(str(path)) + "Concurrent author's note.\r\n"

    def edit_after_planning(config_path, overlay=None):
        project = load(config_path, overlay=overlay)
        if overlay:
            textio.write_text(str(path), concurrent)
        return project

    monkeypatch.setattr(loader, "load_readonly", edit_after_planning)
    result = key_restore.apply(str(tmp_path), [f"REQ-001@{original}"])
    assert not result.ok
    assert result.errors == ["item source changed while planning; retry"]
    assert textio.read_text(str(path)) == concurrent


def test_partial_batch_write_restores_every_original(tmp_path, monkeypatch):
    _config, _path, original, _current = _fixture(tmp_path)
    second = keys.mint()
    (tmp_path / "items/second.md").write_text(
        f"---\nid: REQ-004\nkey: {keys.mint()}\ntype: requirement\ntitle: Second\n---\n"
    )
    before = _snapshot(tmp_path)
    write = revise.write_rewrites

    def fail_after_first(rewrites):
        assert len(rewrites) == 2
        write(rewrites[:1])
        raise OSError("partial write failure")

    monkeypatch.setattr(revise, "write_rewrites", fail_after_first)
    result = key_restore.apply(str(tmp_path), [f"REQ-001@{original}", f"REQ-004@{second}"])
    assert not result.ok
    assert "rolled back" in result.errors[0]
    assert _snapshot(tmp_path) == before
