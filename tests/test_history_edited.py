"""Phase H3: "edited after captured" — a diagnostic and never a failure.

docs/design/living-notes-plan.md §H3 and docs/design/living-notes.md §3.
An item whose snapshot exists in `.refdes/history/` as a followed
predecessor and whose current semantic digest differs from it gets one
WARNING naming the item, the capture event, and the successor — never an
error, never a changed exit code, never a write. The schema declares
`follows:` by hand, the same convention as tests/test_history_capture.py.
"""

from __future__ import annotations

import json
import re

from conftest import write_project_config

from refdes import build as build_mod
from refdes import cli as cli_mod
from refdes import history, loader, render

FOLLOWS_SCHEMA = """\
site: { title: Edited Test, out: ../site_out_edited }
id: { width: 3, ledger: .refdes/ids.yaml }
link_types:
  follows: { inverse: followed_by, label: Follows }
types:
  log:
    prefix: LOG
    append_only: true
    fields:
      summary: { type: text, required: true }
      owner: { type: text, on_change: log }
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


def _edited_warnings(project):
    return [d for d in project.warnings if "edited after captured" in d.message]


def _edit_summary(tmp_path, item_id, new_summary):
    log = tmp_path / "items" / "log.yaml"
    lines = []
    editing = False
    for line in log.read_text(encoding="utf-8").splitlines():
        if line.strip().startswith(f"id: {item_id}"):
            editing = True
        elif editing and line.strip().startswith("id: "):
            editing = False
        lines.append(
            re.sub(r"(summary:\s*).*", r"\g<1>" + new_summary, line)
            if editing and line.strip().startswith("summary:")
            else line
        )
    log.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _repoint_edge(path, new_target):
    lines = [
        "    follows: [%s]" % new_target
        if line.strip().startswith("follows:")
        else line
        for line in path.read_text(encoding="utf-8").splitlines()
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


# ------------------------------------------------------------- the diagnostic


def test_editing_a_captured_entry_warns_once_naming_item_event_successor(
    tmp_path, capsys
):
    """The plan's sabotage case: capture, edit the body, `refdes check` ->
    a warning naming the entry, the capture event, and the successor, with
    the exit code unchanged."""
    cfg = _setup(tmp_path, TWO)
    project, _stale = loader.load_tree(cfg, write=True)
    capsys.readouterr()
    event = history.load_events(str(tmp_path))[0]

    _edit_summary(tmp_path, "LOG-001", "Rewritten after capture.")
    assert cli_mod.main(["-c", cfg, "check"]) == 0
    out = capsys.readouterr().out
    matches = [line for line in out.splitlines() if "edited after captured" in line]
    assert len(matches) == 1
    assert "LOG-001" in matches[0]
    assert event["id"] in matches[0]
    assert "LOG-002" in matches[0]
    assert "warning" in matches[0].lower()
    assert "0 errors" in out


def test_an_unchanged_captured_item_draws_no_diagnostic(tmp_path, capsys):
    cfg = _setup(tmp_path, TWO)
    loader.load_tree(cfg, write=True)
    capsys.readouterr()

    project, _stale = loader.load_tree(cfg, write=True)
    build_mod.build(project)
    assert _edited_warnings(project) == []


def test_the_finding_names_the_item_the_event_and_the_captured_digest(tmp_path):
    """Unit level: `edited_after_captured(project)` returns
    `(item, event, captured_digest)` per the plan."""
    cfg = _setup(tmp_path, TWO)
    project, _stale = loader.load_tree(cfg, write=True)
    _edit_summary(tmp_path, "LOG-001", "Rewritten after capture.")
    project, _stale = loader.load_tree(cfg, write=True)

    findings = history.edited_after_captured(project)
    assert len(findings) == 1
    finding = findings[0]
    assert finding.item is project.item_by_id("LOG-001")
    assert finding.event["kind"] == "followed"
    assert finding.event["successor_key"] == project.item_by_id("LOG-002").key
    assert finding.captured_digest == finding.event["object"]
    assert finding.captured_digest != history.semantic_digest(finding.item)


def test_the_diagnostic_is_a_warning_and_never_fails_a_build(tmp_path, capsys):
    """`refdes build` after the sabotage: site still written, 0 errors,
    exit 0 -- the warning is a signal, not a gate."""
    cfg = _setup(tmp_path, TWO)
    loader.load_tree(cfg, write=True)
    _edit_summary(tmp_path, "LOG-001", "Rewritten after capture.")
    capsys.readouterr()

    assert cli_mod.main(["-c", cfg, "build"]) == 0
    out = capsys.readouterr().out
    assert "0 errors" in out
    assert any("edited after captured" in line for line in out.splitlines())
    site = tmp_path.parent / "site_out_edited"
    assert (site / "index.html").exists()


# ------------------------------------------------- the two-digest split (§3)


def test_an_on_change_log_edit_moves_history_not_the_content_hash(tmp_path):
    """The digest covers what `content_hash` excludes: editing an
    `on_change: log` field is an edit in history's eyes while the baseline
    digest does not move."""
    cfg = _setup(
        tmp_path,
        "defaults: { type: log }\n"
        "items:\n"
        "  - id: LOG-001\n    summary: First.\n    owner: jared\n"
        "  - id: LOG-002\n    summary: Second.\n    follows: [LOG-001]\n",
    )
    project, _stale = loader.load_tree(cfg, write=True)
    build_mod.build(project)
    before_hash = project.item_by_id("LOG-001").content_hash

    log = tmp_path / "items" / "log.yaml"
    log.write_text(
        log.read_text(encoding="utf-8").replace("owner: jared", "owner: someone-else"),
        encoding="utf-8",
    )
    project, _stale = loader.load_tree(cfg, write=True)
    build_mod.build(project)

    warnings = _edited_warnings(project)
    assert len(warnings) == 1
    assert "LOG-001" in warnings[0].message
    assert project.item_by_id("LOG-001").content_hash == before_hash


# ------------------------------------------- corrections, supersession, merges


def test_a_superseded_capture_goes_quiet_and_the_corrected_one_stays_live(
    tmp_path,
):
    """§2 case one at read time: after LOG-002's edge is corrected from
    LOG-001 to LOG-003, editing the wrongly-captured LOG-001 draws no
    warning -- its capture was disowned -- while editing LOG-003 warns and
    names the `followed-corrected` event."""
    cfg = _setup(
        tmp_path,
        TWO + "  - id: LOG-003\n    summary: The one actually meant.\n",
    )
    loader.load_tree(cfg, write=True)
    _repoint_edge(tmp_path / "items" / "log.yaml", "LOG-003")
    loader.load_tree(cfg, write=True)
    corrected = [
        e for e in history.load_events(str(tmp_path)) if e["kind"] == "followed-corrected"
    ]
    assert len(corrected) == 1

    _edit_summary(tmp_path, "LOG-001", "Edited, but nobody captured me live.")
    project, _stale = loader.load_tree(cfg, write=True)
    build_mod.build(project)
    assert _edited_warnings(project) == []

    _edit_summary(tmp_path, "LOG-003", "Edited after the corrected capture.")
    project, _stale = loader.load_tree(cfg, write=True)
    build_mod.build(project)
    warnings = _edited_warnings(project)
    assert len(warnings) == 1
    assert "LOG-003" in warnings[0].message
    assert corrected[0]["id"] in warnings[0].message


def test_a_merge_keeps_both_parent_captures_live(tmp_path):
    """A merge is not a correction (§2): both parents' captures stand, and
    editing one parent warns about that parent only."""
    cfg = _setup(
        tmp_path,
        "defaults: { type: log }\n"
        "items:\n"
        "  - id: LOG-001\n    summary: Root A.\n"
        "  - id: LOG-002\n    summary: Root B.\n"
        "  - id: LOG-003\n    summary: Merged.\n    follows: [LOG-001, LOG-002]\n",
    )
    loader.load_tree(cfg, write=True)
    _edit_summary(tmp_path, "LOG-001", "Root A, edited after capture.")
    project, _stale = loader.load_tree(cfg, write=True)
    build_mod.build(project)

    warnings = _edited_warnings(project)
    assert len(warnings) == 1
    assert "LOG-001" in warnings[0].message
    assert "LOG-002" not in "".join(d.message for d in warnings)


# ------------------------------------------------------------ read-only-ness


def test_a_project_with_no_history_is_silent_and_gains_no_directory(
    tmp_path, capsys
):
    cfg = _setup(
        tmp_path,
        "defaults: { type: log }\nitems:\n  - id: LOG-001\n    summary: Alone.\n",
    )
    assert cli_mod.main(["-c", cfg, "check"]) == 0
    out = capsys.readouterr().out
    assert "edited after captured" not in out
    assert not (tmp_path / ".refdes" / "history").exists()


# ------------------------------------------------------------ the index pair


def test_items_json_carries_the_pair_for_captured_items_only(tmp_path):
    cfg = _setup(tmp_path, TWO)
    project, _stale = loader.load_tree(cfg, write=True)
    build_mod.build(project)
    event = history.load_events(str(tmp_path))[0]

    payload = render.items_json(project)
    by_id = {entry["id"]: entry for entry in payload["items"]}
    assert by_id["LOG-001"]["captured"] == event["id"]
    assert by_id["LOG-001"]["edited_after_captured"] is False
    assert "captured" not in by_id["LOG-002"]
    assert "edited_after_captured" not in by_id["LOG-002"]

    _edit_summary(tmp_path, "LOG-001", "Rewritten after capture.")
    project, _stale = loader.load_tree(cfg, write=True)
    build_mod.build(project)
    payload = render.items_json(project)
    by_id = {entry["id"]: entry for entry in payload["items"]}
    assert by_id["LOG-001"]["edited_after_captured"] is True


def test_items_json_is_unchanged_for_an_uncaptured_project(tmp_path):
    cfg = _setup(
        tmp_path,
        "defaults: { type: log }\nitems:\n  - id: LOG-001\n    summary: Alone.\n",
    )
    project, _stale = loader.load_tree(cfg, write=True)
    build_mod.build(project)
    payload = render.items_json(project)
    assert json  # payload stays parseable JSON; no captured keys anywhere
    for entry in payload["items"]:
        assert "captured" not in entry
        assert "edited_after_captured" not in entry
