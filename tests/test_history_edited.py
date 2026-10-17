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
import os
import re
from pathlib import Path

from conftest import write_project_config

from refdes import build as build_mod
from refdes import cli as cli_mod
from refdes import history, loader, render

FOLLOWS_SCHEMA = """\
site: { title: Edited Test, out: ../site_out_edited }
id: { width: 3, ledger: .refdes/ids.yaml }
link_types:
  follows: { inverse: followed_by, label: Follows }
  amends: { inverse: amended_by, label: Amends }
types:
  log:
    prefix: LOG
    append_only: true
    fields:
      summary: { type: text, required: true }
      owner: { type: text, on_change: timeline }
    links:
      follows: [log]
      amends: [log]
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


def test_an_on_change_timeline_edit_moves_history_not_the_content_hash(tmp_path):
    """The digest covers what `content_hash` excludes: editing an
    `on_change: timeline` field is an edit in history's eyes while the baseline
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


# --------------------------------------------------- the remedy and the pointer


def test_the_warning_carries_the_remedy_and_the_docs_page(tmp_path, capsys):
    """Run-5 F4. The `sealing: build` error this warning replaced ended with
    the one thing a reader can act on -- how an append-only log is edited
    (`Append a new entry with `amends: [LOG-001]` instead`). The warning kept
    the event id and dropped that, so the reader was told their log was
    edited with no hint of what an append-only log is edited by instead, and
    no page to read. `docs/troubleshooting.md`'s own `## The design log`
    section already gives the advice; the diagnostic now points at it."""
    cfg = _setup(tmp_path, TWO)
    loader.load_tree(cfg, write=True)
    capsys.readouterr()

    _edit_summary(tmp_path, "LOG-001", "Rewritten after capture.")
    assert cli_mod.main(["-c", cfg, "check"]) == 0
    lines = [line for line in capsys.readouterr().out.splitlines()
             if "edited after captured" in line]
    assert len(lines) == 1
    assert "amends: [LOG-001]" in lines[0]
    assert (
        "https://squishiba.github.io/refdes/troubleshooting.html#the-design-log"
        in lines[0]
    )


REMEDY_SCOPE_SCHEMA = """\
site: { title: Remedy Scope, out: ../site_out_remedy }
id: { width: 3, ledger: .refdes/ids.yaml }
link_types:
  amends: { inverse: amended_by, label: Amends }
types:
  log:
    prefix: LOG
    append_only: true
    sealing: history
    fields:
      summary: { type: text, required: true }
    links:
      amends: [log]
  memo:
    prefix: MEMO
    fields:
      summary: { type: text, required: true }
"""

ONE_EACH = (
    "items:\n"
    "  - id: LOG-001\n    type: log\n    summary: First entry.\n"
    "  - id: MEMO-001\n    type: memo\n    summary: First memo.\n"
)


def test_the_amends_remedy_is_offered_only_where_following_it_is_legal(
    tmp_path, capsys
):
    """Run-5 F4's remedy names `amends:`, but `amends` is an append-only type's
    verb for correcting its own entries -- the bundled `hardware@3` restricts
    it to `log`, and the project schema here does the same. `history capture`
    takes any keyed item, so a captured `memo` got the same sentence, and doing
    what it says is a build error (`amends may point at log, but MEMO-001 is a
    memo`): the one tool that can spot the edit confidently recommended a
    construct the project's own standard forbids. The advice belongs to the
    append-only entry only; the editable one is told its edit needs nothing
    done about it."""
    write_project_config(tmp_path, REMEDY_SCOPE_SCHEMA)
    items = tmp_path / "items"
    items.mkdir()
    (items / "log.yaml").write_text(ONE_EACH, encoding="utf-8")
    cfg = str(tmp_path / "refdes-project.yaml")
    assert cli_mod.main(["-c", cfg, "build"]) == 0
    for item_id in ("LOG-001", "MEMO-001"):
        assert cli_mod.main(["-c", cfg, "history", "capture", item_id]) == 0
    capsys.readouterr()

    _edit_summary(tmp_path, "LOG-001", "First entry, edited.")
    _edit_summary(tmp_path, "MEMO-001", "First memo, edited.")
    assert cli_mod.main(["-c", cfg, "check"]) == 0
    lines = [
        line for line in capsys.readouterr().out.splitlines()
        if "edited after captured" in line
    ]
    assert len(lines) == 2
    memo = next(line for line in lines if "[MEMO-001]" in line)
    assert "amends" not in memo
    log_line = next(line for line in lines if "[LOG-001]" in line)
    assert "amends: [LOG-001]" in log_line


AMENDS_ABSENT_SCHEMA = """\
site: { title: Amends Absent, out: ../site_out_amends_absent }
id: { width: 3, ledger: .refdes/ids.yaml }
link_types:
  amends: { inverse: amended_by, label: Amends }
types:
  log:
    prefix: LOG
    append_only: true
    sealing: history
    fields:
      summary: { type: text, required: true }
    links:
      amends: [log]
  memo:
    prefix: MEMO
    append_only: true
    sealing: history
    fields:
      summary: { type: text, required: true }
"""


def test_an_append_only_type_without_an_amends_verb_gets_no_amends_advice(
    tmp_path, capsys
):
    """The gate is not `append_only` alone: the `amends:` sentence is advice,
    and advice is only sound where the project's own schema lets an `amends`
    link point at the entry's type. A second append-only type declaring no
    such verb (a project overlay replaces its bundled `log`'s links, so even
    `log` can be in this shape) was still told to `append a new entry with
    `amends: [MEMO-001]``, and following it was a silently-dropped unknown
    field -- the reviewer's residual probe. The warning may *name* the verb
    to explain why it is not offered; it must not tell you to write it, and
    it must not call the type editable. What the warning *does* tell you to
    do (write the `amends:` for the type that declares the verb) is followed
    here and must stay legal."""
    write_project_config(tmp_path, AMENDS_ABSENT_SCHEMA)
    items = tmp_path / "items"
    items.mkdir()
    (items / "log.yaml").write_text(ONE_EACH, encoding="utf-8")
    cfg = str(tmp_path / "refdes-project.yaml")
    assert cli_mod.main(["-c", cfg, "build"]) == 0
    for item_id in ("LOG-001", "MEMO-001"):
        assert cli_mod.main(["-c", cfg, "history", "capture", item_id]) == 0
    capsys.readouterr()

    _edit_summary(tmp_path, "LOG-001", "First entry, edited.")
    _edit_summary(tmp_path, "MEMO-001", "First memo, edited.")
    assert cli_mod.main(["-c", cfg, "check"]) == 0
    lines = [
        line for line in capsys.readouterr().out.splitlines()
        if "edited after captured" in line
    ]
    assert len(lines) == 2
    memo = next(line for line in lines if "[MEMO-001]" in line)
    assert "`amends: [MEMO-001]`" not in memo  # not told to write the link
    assert "type is editable" not in memo  # it is append-only -- do not lie
    log_line = next(line for line in lines if "[LOG-001]" in line)
    assert "amends: [LOG-001]" in log_line

    # Follow the advice that IS given: append a log entry amending LOG-001.
    with (items / "log.yaml").open("a", encoding="utf-8") as fh:
        fh.write(
            "  - id: LOG-002\n    type: log\n"
            "    summary: Correction.\n    amends: [LOG-001]\n"
        )
    assert cli_mod.main(["-c", cfg, "check"]) == 0  # advice leads to 0 errors

    # And following the memo's own wording -- leaving the deliberate edit
    # alone -- also stays green.
    assert cli_mod.main(["-c", cfg, "check"]) == 0


def test_an_unknown_type_is_not_claimed_editable(tmp_path):
    """`spec is None` must not fold into the editable branch: the tool knows
    nothing about an undeclared type, and asserting its editability is a
    claim the code cannot support. A locally parsed item cannot reach this
    (parse refuses an unknown type before it joins the project), but an item
    whose type is simply not in the *local* resolved schema can -- the state
    here is reproduced at API level by dropping the type after the load,
    exactly the shape a foreign item's type has on a board that does not
    declare it."""
    cfg = _setup(tmp_path, TWO)
    loader.load_tree(cfg, write=True)
    _edit_summary(tmp_path, "LOG-001", "Rewritten after capture.")
    project, _stale = loader.load_tree(cfg, write=True)
    del project.types["log"]
    build_mod.warn_edited_after_captured(project)
    warnings = _edited_warnings(project)
    assert len(warnings) == 1
    assert "type is editable" not in warnings[0].message
    assert "Nothing in this project's schema describes the entry's type" in (
        warnings[0].message
    )


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


# ------------------------------------ calc fence labels are labels (run-9 F2)

# docs/math.md calls a ```calc block's `id="..."` a label on the rendering.
# Run 9 found that naming a block of an entry already captured by `follows`
# read as a semantic edit and drew the warning above. The strip lives on
# `semantic_payload`'s body, beside the whitespace collapse it joins: a label
# is not more content than a reflow is.

CALC_LOG = (
    "defaults: { type: log }\n"
    "items:\n"
    "  - id: LOG-001\n    summary: First.\n    body: |\n"
    "      ```calc\n"
    "      P_diss = 3.3 V * 0.5 A | W\n"
    "      ```\n"
    "  - id: LOG-002\n    summary: Second.\n    follows: [LOG-001]\n"
)

CALC_LOG_NAMED = CALC_LOG.replace("```calc\n", '```calc id="thermal"\n')


def _replace_in_log(tmp_path, old, new):
    log = tmp_path / "items" / "log.yaml"
    text = log.read_text(encoding="utf-8")
    assert old in text
    log.write_text(text.replace(old, new), encoding="utf-8")


def test_naming_a_captured_calc_fence_draws_no_diagnostic(tmp_path):
    """The run-9 F2 scenario, end to end: capture, THEN add id="thermal" to
    the calc fence. Sabotage: drop the label strip from `semantic_payload`
    and this is exactly the warning the report got."""
    cfg = _setup(tmp_path, CALC_LOG)
    loader.load_tree(cfg, write=True)  # captures LOG-001 at the follows edge
    _replace_in_log(tmp_path, "```calc\n", '```calc id="thermal"\n')
    project, _stale = loader.load_tree(cfg, write=True)
    build_mod.build(project)
    assert _edited_warnings(project) == []


def test_renaming_a_captured_calc_fence_label_draws_no_diagnostic(tmp_path):
    """A label is a label in both directions: `thermal` -> `hot` after the
    capture is a rendering edit, not a content edit. Sabotage: hashing any
    part of the fence's info string fails this."""
    cfg = _setup(tmp_path, CALC_LOG_NAMED)
    loader.load_tree(cfg, write=True)
    _replace_in_log(tmp_path, 'id="thermal"', 'id="hot"')
    project, _stale = loader.load_tree(cfg, write=True)
    build_mod.build(project)
    assert _edited_warnings(project) == []


def test_editing_a_row_inside_a_captured_fence_is_still_an_edit(tmp_path):
    """The strip takes the label off the fence line, not the block's rows:
    0.5 A -> 0.6 A under a named fence remains an edit, warned once and
    naming the entry. Sabotage: a strip that swallows the block -- or all
    fenced content -- silences this."""
    cfg = _setup(tmp_path, CALC_LOG_NAMED)
    loader.load_tree(cfg, write=True)
    _replace_in_log(tmp_path, "0.5 A", "0.6 A")
    project, _stale = loader.load_tree(cfg, write=True)
    build_mod.build(project)
    warnings = _edited_warnings(project)
    assert len(warnings) == 1
    assert "LOG-001" in warnings[0].message


def test_the_label_strip_leaves_unlabelled_digests_byte_identical(tmp_path):
    """Every digest minted before the strip stays valid: for an item with no
    labelled calc fence the semantic digest is exactly what the pre-strip
    formula produced -- sha256 over the canonical JSON of
    `{history_format, type, fields, links, _collapse_ws(body)}` -- so
    existing stores keep matching, item for item. Sabotage: a payload-shape
    change (a new key, a normalization the collapse does not absorb, a strip
    that reaches an unlabelled body) moves one of these two digests."""
    cfg = _setup(tmp_path, CALC_LOG)
    project, _stale = loader.load_tree(cfg, write=True)
    for item_id in ("LOG-001", "LOG-002"):
        item = project.item_by_id(item_id)
        assert history.semantic_digest(item) == history.digest_of(
            {
                "history_format": history.HISTORY_FORMAT,
                "type": item.type,
                "fields": item.fields,
                "links": item.links,
                "body": history._collapse_ws(item.body),
            }
        )


# ------------------- pre-#323 labelled captures are not "edited" (run-10 F5)

# PR #323 took a ```calc fence's `id="..."` out of the semantic digest. A
# LABELLED fence captured before that change stored a digest hashing the
# label text, so the current digest matches no stored event and the entry
# reports `edited after captured` with nobody having edited it -- run-10
# F5, the release blocker, whose documented remedy (`history capture`) the
# one-capture-per-item rule refuses. The fixture replays such a capture:
# the digest, object and event the old code wrote, built from
# `legacy_semantic_payload`/`legacy_object_payload` (the exact payload the
# old digest hashed), not from a captured store binary.

CALC_ONE = (
    "defaults: { type: log }\n"
    "items:\n"
    "  - id: LOG-001\n    summary: First.\n    body: |\n"
    "      ```calc\n"
    "      P_diss = 3.3 V * 0.5 A | W\n"
    "      ```\n"
)

CALC_ONE_NAMED = CALC_ONE.replace("```calc\n", '```calc id="losses"\n')


def _capture_pre_323(root, item_id):
    """Write the object + `captured` event the pre-#323 code would have
    written for ``item_id``: the digest is over the legacy payload, labels
    included."""
    project, _stale = loader.load_tree(str(Path(root) / "refdes-project.yaml"), write=True)
    item = project.item_by_id(item_id)
    digest = history.legacy_semantic_digest(item)
    path = history.object_path(root, digest)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    Path(path).write_text(
        history._format_yaml(
            history.legacy_object_payload(item), history._OBJECT_HEADER
        ),
        encoding="utf-8",
    )
    history.append_event(root, "captured", item.key, digest, reason="manual capture")


def test_a_pre_323_labelled_capture_is_not_edited_when_unchanged(tmp_path):
    """R10-F5 at the digest layer: captured with the pre-#323 digest, edited
    by nobody, checked by the current code -> no warning. Red on main: the
    current digest strips the label, so the stored event matches nothing.
    Sabotage: drop the legacy digest from the comparison and the report's
    permanent false warning is back."""
    cfg = _setup(tmp_path, CALC_ONE_NAMED)
    _capture_pre_323(tmp_path, "LOG-001")
    project, _stale = loader.load_tree(cfg, write=True)
    build_mod.build(project)
    assert _edited_warnings(project) == []
    assert history.edited_after_captured(project) == []


def test_a_pre_323_labelled_capture_still_warns_on_a_prose_edit(tmp_path):
    """The compatibility comparison opens the door on labels only: prose is
    content, so a real edit of a pre-#323 capture warns exactly as before."""
    cfg = _setup(tmp_path, CALC_ONE_NAMED)
    _capture_pre_323(tmp_path, "LOG-001")
    _edit_summary(tmp_path, "LOG-001", "Rewritten after the upgrade.")
    project, _stale = loader.load_tree(cfg, write=True)
    build_mod.build(project)
    warnings = _edited_warnings(project)
    assert len(warnings) == 1
    assert "LOG-001" in warnings[0].message


def test_a_pre_323_labelled_capture_still_warns_on_a_calc_row_edit(tmp_path):
    """Rows inside the fence stayed content through #323, and the legacy
    comparison keeps them content: a pre-#323 capture with an edited row
    warns, label and all."""
    cfg = _setup(tmp_path, CALC_ONE_NAMED)
    _capture_pre_323(tmp_path, "LOG-001")
    _replace_in_log(tmp_path, "0.5 A", "0.6 A")
    project, _stale = loader.load_tree(cfg, write=True)
    build_mod.build(project)
    warnings = _edited_warnings(project)
    assert len(warnings) == 1
    assert "LOG-001" in warnings[0].message


def test_a_label_rename_after_the_upgrade_stays_silent(tmp_path):
    """Decided in the fix and documented in `capture_index`: a label is not
    semantic, so a label-only edit made after the upgrade of a pre-#323
    capture must not warn either -- the stored snapshot digested under the
    current (label-stripping) formula equals the current digest. Sabotage:
    compare the raw stored digest only, and renaming a label of an old
    capture is an "edit"."""
    cfg = _setup(tmp_path, CALC_ONE_NAMED)
    _capture_pre_323(tmp_path, "LOG-001")
    _replace_in_log(tmp_path, 'id="losses"', 'id="burn"')
    project, _stale = loader.load_tree(cfg, write=True)
    build_mod.build(project)
    assert _edited_warnings(project) == []


def test_an_unlabelled_capture_behaves_the_same_under_either_digest(tmp_path):
    """#323's byte-for-byte guarantee, on the comparison side: with no label
    in the body the legacy and current digests are one digest, so a pre-#323
    capture matches the current digest directly -- silent before the fix and
    silent after, and its real edits warn as they always did."""
    cfg = _setup(tmp_path, CALC_ONE)
    _capture_pre_323(tmp_path, "LOG-001")
    project, _stale = loader.load_tree(cfg, write=True)
    build_mod.build(project)
    assert _edited_warnings(project) == []

    _edit_summary(tmp_path, "LOG-001", "Rewritten after capture.")
    project, _stale = loader.load_tree(cfg, write=True)
    build_mod.build(project)
    warnings = _edited_warnings(project)
    assert len(warnings) == 1
    assert "LOG-001" in warnings[0].message


def test_an_entry_captured_by_the_current_code_stays_silent(tmp_path):
    """The capture side of #323, end to end: a labelled fence captured by
    the current code digests exactly as the current formula, so the check
    right after the capture is silent and stays silent through a label
    rename."""
    cfg = _setup(tmp_path, CALC_ONE_NAMED)
    assert cli_mod.main(["-c", cfg, "history", "capture", "LOG-001"]) == 0
    project, _stale = loader.load_tree(cfg, write=True)
    build_mod.build(project)
    assert _edited_warnings(project) == []

    _replace_in_log(tmp_path, 'id="losses"', 'id="burn"')
    project, _stale = loader.load_tree(cfg, write=True)
    build_mod.build(project)
    assert _edited_warnings(project) == []


def test_the_legacy_digest_is_the_pre_323_formula(tmp_path):
    """The legacy payload is exactly what the digest hashed before #323:
    sha256 over the canonical JSON of
    `{history_format, type, fields, links, _collapse_ws(body)}` -- the
    formula `test_the_label_strip_leaves_unlabelled_digests_byte_identical`
    pins as pre-strip. Sabotage: change the legacy payload's shape and an
    old store stops matching."""
    cfg = _setup(tmp_path, CALC_ONE_NAMED)
    project, _stale = loader.load_tree(cfg, write=True)
    item = project.item_by_id("LOG-001")
    assert history.legacy_semantic_digest(item) == history.digest_of(
        {
            "history_format": history.HISTORY_FORMAT,
            "type": item.type,
            "fields": item.fields,
            "links": item.links,
            "body": history._collapse_ws(item.body),
        }
    )


def test_a_legacy_digest_match_survives_an_unshared_snapshot(tmp_path):
    """The legacy digest is not only the cheap path: a project that commits
    the capture events without the snapshot bodies -- the events are the
    audit trail, the objects are the content, and a privacy-shaped project
    keeps exactly one of the two -- has no stored body to re-digest, so the
    digest comparison is the only comparison left standing. Sabotage: drop
    the legacy digest from the comparison and an unedited pre-#323 capture
    of that shape warns again."""
    cfg = _setup(tmp_path, CALC_ONE_NAMED)
    _capture_pre_323(tmp_path, "LOG-001")
    objects = tmp_path / ".refdes" / "history" / "objects"
    for name in os.listdir(objects):
        os.remove(objects / name)
    project, _stale = loader.load_tree(cfg, write=True)
    build_mod.build(project)
    assert _edited_warnings(project) == []
