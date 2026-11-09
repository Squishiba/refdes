"""The continuation apply-operation: `serve.edit.continue_thread` (docs/design/
thread-workbench-w5b-plan.md §4 W5b.1).

W5b.1 is the server-side half of §7a.2's "Ticking collects into a draft": one
operation that takes (thread ref, {task id -> wanted state}, expected revision)
and writes exactly one continuation entry -- the tip's copied-and-updated
complete `tasks:` list appended to the thread's own file by the creation
machinery -- never a mutation of the tip. No HTTP, no pane, no CLI: this file
tests the operation at the same level `tests/test_serve_edit.py` and
`tests/test_serve_create.py` test their entry points.

The signature this file pins; the implementer follows it (the plan's W5b.1
"Adds" paragraph, plan lines 229-234, plus the neighbours' shapes):

    edit.continue_thread(project_root, request, config_path=None, *, read_only=False)
        -> Applied | Conflict | Refused | Invalid

    @dataclass(frozen=True)
    class ContinueRequest:
        who: str                                # the permissions seam, as every op
        ref: str                                # an entry of the thread (its tip)
        ticks: tuple[tuple[str, str], ...]      # (task id, wanted state), in order
        expected_revision: str                  # file_revision of the thread's file

* Entry-point shape mirrors `apply_edit`/`create_item` exactly: positional
  `project_root`, a frozen request carrying `who` (the module's permission
  seam, `edit.py`'s docstring), optional `config_path`.
* `ticks` is a sequence of pairs, not a mapping: W5b.1's verified-against list
  refuses "a second tick for the same id" (plan line 243), which a mapping --
  or a JSON object a parser collapses -- cannot express.
* `read_only` is keyword-only on the entry point: W5b.1 has no HTTP face, so
  the `--no-write` gate (the refusal text the sibling routes spell,
  `api.py:1168`) is the operation's to honour from the caller's flag; W5b.2's
  route passes `app.read_only` in.
* One of the four existing result values (plan line 231, "returns one of the
  existing four result values"); `Applied` reports the new entry's id/path/
  revision as `Created` reports a creation's, `Conflict` carries the current
  disk text (plan lines 266-268: a request that lies about the revision ->
  `Conflict` with the current list, and no write).
* `expected_revision` is the content revision of the thread's own file, the
  same spelling `EditRequest.expected_revision` documents (plan line 106).

Ratified defaults this file pins (Jared, 2026-11-06 -- every "Conservative
default" in plan §6 is the spec; the plan lines cited in each test): Q2(a)+(i)
copy the tip's declared fields verbatim, body empty; Q3(a) revision compare;
Q4 the operation names the TIP -- an older entry's page continues the tip;
Q6(b) un-ticking lands (a change on a non-open row is not refused merely
because the row is not open), and the offered verbs are open->done/dropped and
*->open, so a change between two non-open states is refused; R2 the tip's
bytes unchanged; R5 a refusal burns no id.
"""

from __future__ import annotations

import os
import threading
from datetime import date

import pytest
from conftest import write_project_config

from refdes import build as build_mod
from refdes import chains, dates, keys, links, parse
from refdes.model import TASK_STATES
from refdes.schema import load_project
from refdes.serve import edit as edit_mod
from refdes.serve.edit import Applied, Conflict, Invalid, Refused

SCHEMA = """\
site:
  title: "Continue test"
date_format: DD/MM/YYYY
id:
  width: 3
link_types:
  follows: { inverse: followed_by, label: Follows, trace: false }
types:
  log:
    prefix: LOG
    append_only: true
    fields:
      date: { type: date }
      summary: { type: text, required: true }
      tasks: { type: tasks, on_change: timeline }
    links:
      follows: [log]
"""

# The thread's own file: a `defaults.prefix` series (the id proof, plan line
# 245), a settled thread whose tip declares the complete list -- one row in
# each state the ratified Q6(b) vocabulary offers, so every transition rule
# this file pins has a live row.
LOG = """\
defaults:
  type: log
  prefix: LOG-SYS

items:
  - id: LOG-SYS-001
    summary: Rail work opens.
    date: 30/08/2026
  - id: LOG-SYS-002
    summary: Rail work continues.
    date: 01/09/2026
    follows: [LOG-SYS-001]
    tasks:
      - {id: T-rail, text: Settle the rail budget., state: open}
      - {id: T-bom, text: Freeze the BOM., state: done}
      - {id: T-old, text: Retire the old antenna., state: dropped}
      - {id: T-probe, text: Probe the SWD pins., state: open}
"""

# The same thread shape in a multi-item Markdown file (the append-md shape,
# plan lines 114-117): a first `defaults:` block donates the prefix series.
NOTES_MD = """\
---
defaults:
  type: log
  prefix: LOG-MD
---

---
id: LOG-MD-001
summary: Bring-up opens.
date: 30/08/2026
---

---
id: LOG-MD-002
summary: Bring-up continues.
date: 01/09/2026
follows: [LOG-MD-001]
tasks: [{id: T-boot, text: Measure idle current., state: open}]
---
"""


def _write(root, name, text):
    with open(os.path.join(str(root), name), "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)


@pytest.fixture
def project_root(tmp_path):
    """The settled thread on a YAML list file, keys minted -- the composite
    `follows:` needs the tip's key, the way any writable command leaves it
    (the `mint_keys` posture of tests/test_serve_create.py)."""
    write_project_config(tmp_path, SCHEMA)
    os.mkdir(os.path.join(str(tmp_path), "items"))
    _write(tmp_path, "items/log.yaml", LOG)
    _write(tmp_path, "items/notes.md", NOTES_MD)
    _mint_keys(tmp_path)
    return tmp_path


def _mint_keys(root):
    project = load_project(config_path=str(root / "refdes-project.yaml"))
    parse.load_items(project)
    keys.mint_missing(project, write=True)


def _mint_and_seal(root):
    """Mint keys, then one writable build: the clean append-only entries gain
    seal records -- the state `apply_edit` refuses to edit (plan line 104)."""
    _mint_keys(root)
    config = str(root / "refdes-project.yaml")
    project = load_project(config_path=config)
    parse.load_items(project)
    build_mod.build(project, seal_write=True, reseal=False)


def _load(root):
    project = load_project(config_path=str(root / "refdes-project.yaml"))
    parse.load_items(project, require_ids=False)
    return project


def _read_bytes(root, rel):
    with open(os.path.join(str(root), rel), "rb") as fh:
        return fh.read()


def tree(root, *subdirs) -> dict[str, str]:
    """relpath -> sha256 for every file under the given subdirectories (the
    sabotage shape of tests/test_serve_create.py: every "no" is also "bytes
    identical")."""
    import hashlib

    files = {}
    for sub in subdirs:
        base = os.path.join(str(root), sub)
        for dirpath, _dirs, names in os.walk(base):
            for name in names:
                path = os.path.join(dirpath, name)
                rel = os.path.relpath(path, str(root)).replace("\\", "/")
                with open(path, "rb") as fh:
                    files[rel] = hashlib.sha256(fh.read()).hexdigest()
    return files


def continue_thread(
    root, ref, ticks, expected_revision, *, who="local-author", read_only=False, config_path=None
):
    """`edit.continue_thread` as this file's contract names it (docstring).
    The attribute access is the red: today the module has neither name."""
    ContinueRequest = edit_mod.ContinueRequest
    request = ContinueRequest(
        who=who, ref=ref, ticks=tuple(ticks), expected_revision=expected_revision
    )
    args = [str(root), request]
    if config_path is not None:
        args.append(config_path)
    return edit_mod.continue_thread(*args, read_only=read_only)


def _tip_revision(root, rel="items/log.yaml"):
    return edit_mod.file_revision(os.path.join(str(root), rel))


def _fold_tip(root, ref):
    """(tip_id, rows, ambiguous) of the fold `ref`'s thread -- the pane's own
    read (`chains.fold_tasks`, plan line 71) over a freshly loaded project."""
    project = _load(root)
    item = project.item_by_id(ref)
    folds = chains.fold_tasks(project, item)
    assert len(folds) == 1, [(f.tip.id, f.rows) for f in folds]
    fold = folds[0]
    return fold.tip.id, fold.rows, fold.ambiguous


# ------------------------------------------------------- the happy path (W5b.1)


def test_continuation_appends_one_entry_carrying_the_whole_updated_list(project_root):
    """The complete-list invariant (plan lines 239-241): the written entry
    carries the tip's WHOLE list -- every untouched row verbatim (id, text,
    state), ticked rows in the wanted state, nothing dropped, order
    preserved -- and the result is an `Applied` naming the new entry."""
    result = continue_thread(
        project_root,
        "LOG-SYS-002",
        [("T-rail", "done"), ("T-probe", "dropped")],
        _tip_revision(project_root),
    )
    assert isinstance(result, Applied), result.message
    assert result.ok
    assert result.who == "local-author"
    assert result.item_id == "LOG-SYS-003"  # the file's own defaults.prefix series
    assert os.path.basename(result.path) == "log.yaml"
    assert result.revision == _tip_revision(project_root)

    # The next fold (a fresh project load) reports the new entry as the tip
    # with the complete updated list, in order.
    tip_id, rows, ambiguous = _fold_tip(project_root, "LOG-SYS-003")
    assert (tip_id, ambiguous) == ("LOG-SYS-003", False)
    assert rows == [
        {"id": "T-rail", "text": "Settle the rail budget.", "state": "done"},
        {"id": "T-bom", "text": "Freeze the BOM.", "state": "done"},
        {"id": "T-old", "text": "Retire the old antenna.", "state": "dropped"},
        {"id": "T-probe", "text": "Probe the SWD pins.", "state": "dropped"},
    ]


def test_the_continuation_copies_the_tips_declared_fields_and_names_its_tip(project_root):
    """The ratified Q2 default (plan lines 426-442): copy the tip's own
    declared fields verbatim (summary, date carry over), the new entry mints
    its own id/key, and `follows:` names the tip as the composite
    `links.composite_for` spells -- server-decided, never client text
    (plan line 246)."""
    tip_key = _load(project_root).item_by_id("LOG-SYS-002").key
    result = continue_thread(
        project_root, "LOG-SYS-002", [("T-rail", "done")], _tip_revision(project_root)
    )
    assert isinstance(result, Applied), result.message

    text = _read_bytes(project_root, "items/log.yaml").decode("utf-8")
    new_block = text.split("- id: LOG-SYS-003", 1)[1]
    assert f"key: {result.handle}" in new_block
    assert f"follows: [LOG-SYS-002@{tip_key}]" in text
    assert "summary: Rail work continues." in new_block  # the tip's, verbatim
    assert "date: 01/09/2026" in new_block  # the tip's, verbatim

    project = _load(project_root)
    new = project.item_by_id("LOG-SYS-003")
    assert new.key and new.key != tip_key
    assert new.links["follows"] == [f"LOG-SYS-002@{tip_key}"]


def test_non_ascii_task_text_is_written_as_is_not_escaped(tmp_path):
    r"""The copied list must stay readable in a hand-authored file: the flow
    dump writes non-ASCII row text as itself (é, —, Ω), not as `\xNN`/`\uNNNN`
    escapes, and the reloaded row text equals the original."""
    write_project_config(tmp_path, SCHEMA)
    os.mkdir(os.path.join(str(tmp_path), "items"))
    row_text = "Résumé — 5 Ω ≤ 3 µF"
    _write(
        tmp_path,
        "items/log.yaml",
        "defaults: { type: log }\n"
        "items:\n"
        "  - {id: LOG-A, summary: Opens., date: 01/09/2026, tasks: "
        f"[{{id: T-a, text: {row_text}, state: open}}]}}\n",
    )
    _mint_keys(tmp_path)

    result = continue_thread(
        tmp_path, "LOG-A", [("T-a", "done")], _tip_revision(tmp_path, "items/log.yaml")
    )
    assert isinstance(result, Applied), result.message

    text = _read_bytes(tmp_path, "items/log.yaml").decode("utf-8")
    new_block = text.split(f"- id: {result.item_id}", 1)[1]
    assert row_text in new_block
    assert "\\x" not in new_block.lower()
    assert "\\u" not in new_block.lower()

    tip_id, rows, ambiguous = _fold_tip(tmp_path, result.item_id)
    assert (tip_id, ambiguous) == (result.item_id, False)
    assert rows == [{"id": "T-a", "text": row_text, "state": "done"}]


def test_the_continuation_copies_scalars_and_lets_the_fold_carry_the_rest(tmp_path):
    """The scalar-only decision (#448 review, 2026-11-07): the new entry
    carries the tip's scalars, the ticked list and the generated `follows:`
    -- and nothing else. A list-typed field and a non-`follows` link declared
    at the tip are NOT re-declared, because the fold carries them from the
    earlier entries and copying them would duplicate edges and checks;
    `chains.resolve_current` on the new entry still answers the tip's value."""
    schema_m1 = SCHEMA.replace(
        "      tasks: { type: tasks, on_change: timeline }",
        "      tags: { type: list, on_change: ignore }\n"
        "      tasks: { type: tasks, on_change: timeline }",
    ).replace(
        "link_types:\n  follows: { inverse: followed_by, label: Follows, trace: false }",
        "link_types:\n"
        "  follows: { inverse: followed_by, label: Follows, trace: false }\n"
        "  relates: { inverse: related_to, label: Relates, trace: false }",
    ).replace(
        "    links:\n      follows: [log]",
        "    links:\n      follows: [log]\n      relates: [log]",
    )
    write_project_config(tmp_path, schema_m1)
    os.mkdir(os.path.join(str(tmp_path), "items"))
    _write(
        tmp_path,
        "items/log.yaml",
        "defaults: { type: log }\n"
        "items:\n"
        "  - {id: LOG-A, summary: Opens., date: 01/09/2026}\n"
        "  - {id: LOG-B, summary: Continues., date: 02/09/2026, follows: [LOG-A], "
        "tags: [bring-up, thermal], relates: [LOG-A], "
        "tasks: [{id: T-a, text: A., state: open}]}\n",
    )
    _mint_keys(tmp_path)
    tip_key = _load(tmp_path).item_by_id("LOG-B").key

    result = continue_thread(
        tmp_path, "LOG-B", [("T-a", "done")], _tip_revision(tmp_path, "items/log.yaml")
    )
    assert isinstance(result, Applied), result.message

    text = _read_bytes(tmp_path, "items/log.yaml").decode("utf-8")
    new_block = text.split(f"- id: {result.item_id}", 1)[1]
    assert "summary: Continues." in new_block  # the scalars carry over
    assert "date: 02/09/2026" in new_block
    assert "tasks: [{id: T-a, text: A., state: done}]" in new_block
    assert "tags:" not in new_block  # the list field is not re-declared
    assert "relates:" not in new_block  # links other than follows are not

    project = _load(tmp_path)
    new = project.item_by_id(result.item_id)
    assert new.links == {"follows": [f"LOG-B@{tip_key}"]}
    # nothing was lost: the fold carries the tip's list field to the new entry
    assert chains.resolve_current(project, new, "tags") == ["bring-up", "thermal"]


def test_the_invented_date_is_written_the_way_the_emitter_writes_it(tmp_path):
    """The date fallback rides the same emitter as every other field: under
    a `YYYY-MM-DD` format the bare `date: 2026-11-07` line reloads as a YAML
    date, not the string -- the emitted line must be quoted the way
    `create_item` writes it, and the reloaded field is that string."""
    schema_yyyy = SCHEMA.replace("date_format: DD/MM/YYYY", "date_format: YYYY-MM-DD")
    write_project_config(tmp_path, schema_yyyy)
    os.mkdir(os.path.join(str(tmp_path), "items"))
    _write(
        tmp_path,
        "items/log.yaml",
        "defaults: { type: log }\n"
        "items:\n"
        "  - {id: LOG-A, summary: Opens., tasks: [{id: T-a, text: A., state: open}]}\n",
    )
    _mint_keys(tmp_path)

    result = continue_thread(
        tmp_path, "LOG-A", [("T-a", "done")], _tip_revision(tmp_path, "items/log.yaml")
    )
    assert isinstance(result, Applied), result.message

    project = _load(tmp_path)
    new = project.item_by_id(result.item_id)
    assert new.fields["date"] == dates.format_date(date.today(), "YYYY-MM-DD")


# ---------------------------------------------------------------- R2: tip bytes


def test_the_tip_entry_bytes_are_unchanged_the_yaml_list_file_gains_a_pure_suffix(
    project_root,
):
    """R2 (plan lines 369-372): the operation writes an append-only suffix --
    every pre-existing byte of the thread's file (the tip included) stays
    exactly where it was, byte for byte."""
    before = _read_bytes(project_root, "items/log.yaml")

    result = continue_thread(
        project_root, "LOG-SYS-002", [("T-rail", "done")], _tip_revision(project_root)
    )
    assert isinstance(result, Applied), result.message

    after = _read_bytes(project_root, "items/log.yaml")
    assert after.startswith(before)  # pure suffix: the tip's bytes untouched
    assert len(after) > len(before)


def test_the_markdown_thread_gains_the_continuation_and_keeps_its_bytes(project_root):
    """The append-md shape (plan lines 114-117): the new entry lands in the
    thread's own Markdown file, the file's pre-existing bytes are a pure
    prefix of the result, its id numbers under the file's first-block
    `defaults.prefix`, and the fold of a fresh load reports the tip's updated
    list (end-to-end, task pin 10)."""
    path = os.path.join(str(project_root), "items/notes.md")
    before = _read_bytes(project_root, "items/notes.md")

    result = continue_thread(
        project_root,
        "LOG-MD-002",
        [("T-boot", "done")],
        edit_mod.file_revision(path),
    )
    assert isinstance(result, Applied), result.message
    assert result.item_id == "LOG-MD-003"

    after = _read_bytes(project_root, "items/notes.md")
    assert after.startswith(before)  # pure append: existing bytes untouched
    tip_id, rows, ambiguous = _fold_tip(project_root, "LOG-MD-003")
    assert (tip_id, ambiguous) == ("LOG-MD-003", False)
    assert rows == [{"id": "T-boot", "text": "Measure idle current.", "state": "done"}]


# --------------------------------------------------------------- refusals, "no"


def _refused(result, needle):
    assert isinstance(result, (Refused, Invalid)), f"expected a refusal, got {result!r}"
    assert not result.ok
    assert result.message  # every result carries a human-readable message
    if isinstance(result, Refused):
        assert needle in result.reason, result.reason
    else:
        assert result.diagnostics
        assert needle in result.message, result.message


def test_the_ambiguous_fold_posture_is_refused_with_nothing_written(tmp_path):
    """Plan line 242: a fold whose walk found differing equal-distance
    declarations ("task reconciliation required") carries no list to copy."""
    write_project_config(tmp_path, SCHEMA)
    os.mkdir(os.path.join(str(tmp_path), "items"))
    _write(
        tmp_path,
        "items/log.yaml",
        "defaults: { type: log }\n"
        "items:\n"
        "  - {id: LOG-C, summary: Left., date: 01/09/2026, tasks: [{id: T-l, text: Left., state: open}]}\n"
        "  - {id: LOG-D, summary: Right., date: 01/09/2026, tasks: [{id: T-r, text: Right., state: open}]}\n"
        "  - {id: LOG-E, summary: Merge., date: 02/09/2026, follows: [LOG-C, LOG-D]}\n",
    )
    _mint_keys(tmp_path)
    before = tree(tmp_path, "items", ".refdes")

    result = continue_thread(
        tmp_path, "LOG-E", [("T-l", "done")], _tip_revision(tmp_path)
    )
    _refused(result, "ambiguous")
    assert tree(tmp_path, "items", ".refdes") == before


def test_the_undeclared_fold_posture_is_refused_with_nothing_written(tmp_path):
    """Plan line 242: nothing in the ancestry declared `tasks:` -- there is
    no list, not an empty one (`rows is None`), so a tick implies a list the
    fold cannot supply."""
    write_project_config(tmp_path, SCHEMA)
    os.mkdir(os.path.join(str(tmp_path), "items"))
    _write(
        tmp_path,
        "items/log.yaml",
        "defaults: { type: log }\n"
        "items:\n"
        "  - {id: LOG-A, summary: Opens., date: 01/09/2026}\n"
        "  - {id: LOG-B, summary: Silent., date: 02/09/2026, follows: [LOG-A]}\n",
    )
    _mint_keys(tmp_path)
    before = tree(tmp_path, "items", ".refdes")

    result = continue_thread(
        tmp_path, "LOG-B", [("T-a", "done")], _tip_revision(tmp_path)
    )
    _refused(result, "undeclared")
    assert tree(tmp_path, "items", ".refdes") == before


def test_the_cleared_fold_posture_is_refused_with_nothing_written(tmp_path):
    """Plan line 242: an explicit `tasks: []` at the tip is a declaration
    that CLEARED the list -- copying it and ticking a row of it would invent
    rows the fold says do not exist."""
    write_project_config(tmp_path, SCHEMA)
    os.mkdir(os.path.join(str(tmp_path), "items"))
    _write(
        tmp_path,
        "items/log.yaml",
        "defaults: { type: log }\n"
        "items:\n"
        "  - {id: LOG-A, summary: Opens., date: 01/09/2026, tasks: [{id: T-a, text: A., state: open}]}\n"
        "  - {id: LOG-B, summary: Cleared., date: 02/09/2026, follows: [LOG-A], tasks: []}\n",
    )
    _mint_keys(tmp_path)
    before = tree(tmp_path, "items", ".refdes")

    result = continue_thread(
        tmp_path, "LOG-B", [("T-a", "done")], _tip_revision(tmp_path)
    )
    _refused(result, "cleared")
    assert tree(tmp_path, "items", ".refdes") == before


def test_an_unknown_task_id_is_refused_with_nothing_written(project_root):
    """Plan line 243: a tick naming a row the tip's list does not carry is a
    refusal -- the server never invents rows (R1: the list is the fold's)."""
    before = tree(project_root, "items", ".refdes")

    result = continue_thread(
        project_root, "LOG-SYS-002", [("T-nope", "done")], _tip_revision(project_root)
    )
    _refused(result, "T-nope")
    assert tree(project_root, "items", ".refdes") == before


def test_a_wanted_state_outside_the_task_vocabulary_is_refused(project_root):
    """Plan line 243: `TASK_STATES` is the whole vocabulary (open, done,
    dropped) -- a tick for `closed` is the typo `build.validate_items`
    exists for, refused at the gate, not copied into an entry."""
    assert TASK_STATES == ("open", "done", "dropped")
    before = tree(project_root, "items", ".refdes")

    result = continue_thread(
        project_root, "LOG-SYS-002", [("T-rail", "closed")], _tip_revision(project_root)
    )
    _refused(result, "closed")
    assert tree(project_root, "items", ".refdes") == before


def test_two_ticks_for_the_same_id_are_refused(project_root):
    """Plan line 243: a second tick for one id is the pane's own double-tap
    made visible at the wire -- refused, not resolved by taking the last."""
    before = tree(project_root, "items", ".refdes")

    result = continue_thread(
        project_root,
        "LOG-SYS-002",
        [("T-rail", "done"), ("T-rail", "dropped")],
        _tip_revision(project_root),
    )
    _refused(result, "T-rail")
    assert tree(project_root, "items", ".refdes") == before


def test_a_sealed_tip_is_refused_and_untouched(project_root):
    """Plan line 243: a sealed (history-recorded, build-sealed) tip is a
    target the write path refuses under the lock, the same refusal
    `apply_edit` makes (plan line 104: sealed-item refusal)."""
    _mint_and_seal(project_root)
    from refdes import seal as seal_mod

    sealed = _load(project_root).item_by_id("LOG-SYS-002")
    assert seal_mod.is_sealed(_load(project_root), sealed)
    before = tree(project_root, "items", ".refdes")

    result = continue_thread(
        project_root, "LOG-SYS-002", [("T-rail", "done")], _tip_revision(project_root)
    )
    _refused(result, "sealed")
    assert tree(project_root, "items", ".refdes") == before


# ------------------------------------------------------- the ratified Q6 (b)


def test_unticking_done_and_dropped_rows_back_to_open_lands(project_root):
    """The ratified Q6 default (b) (plan lines 528-531): "un-ticking a row
    in the draft is free... writing an entry that flips a row back to `open`
    is a true record of the author's current judgment". A change on a row
    that is NOT open is not refused merely for that -- plan lines 634-635
    name this as the (a)-only flag, which Jared did not pick."""
    result = continue_thread(
        project_root,
        "LOG-SYS-002",
        [("T-bom", "open"), ("T-old", "open")],
        _tip_revision(project_root),
    )
    assert isinstance(result, Applied), result.message

    _tip_id, rows, _ambiguous = _fold_tip(project_root, result.item_id)
    assert rows == [
        {"id": "T-rail", "text": "Settle the rail budget.", "state": "open"},
        {"id": "T-bom", "text": "Freeze the BOM.", "state": "open"},
        {"id": "T-old", "text": "Retire the old antenna.", "state": "open"},
        {"id": "T-probe", "text": "Probe the SWD pins.", "state": "open"},
    ]


def test_a_change_between_two_non_open_states_is_refused(project_root):
    """Q6(b) as ratified (plan lines 517-519) is the verb set
    open->done, open->dropped, done->open, dropped->open -- full three-way
    cycling is option (c), not the default. A done->dropped tick is refused;
    a refusal writes nothing."""
    before = tree(project_root, "items", ".refdes")

    result = continue_thread(
        project_root, "LOG-SYS-002", [("T-bom", "dropped")], _tip_revision(project_root)
    )
    _refused(result, "T-bom")
    assert tree(project_root, "items", ".refdes") == before


# ------------------------------------------------------------ id/key, R5 (burn)


def test_the_id_comes_from_the_destination_files_own_prefix_series(project_root):
    """Plan line 245, the proof `tests/test_serve_create.py` makes for
    creation (test_create_uses_the_destination_files_prefix_not_the_bare_type_
    prefix): the new entry's id numbers under the DESTINATION file's
    `defaults.prefix` (LOG-SYS), never the type's bare prefix (LOG), and the
    ledger reserves it."""
    before_ledger = tree(project_root, ".refdes")

    result = continue_thread(
        project_root, "LOG-SYS-002", [("T-rail", "done")], _tip_revision(project_root)
    )
    assert isinstance(result, Applied), result.message
    assert result.item_id == "LOG-SYS-003"

    ledger = os.path.join(str(project_root), ".refdes", "ids.yaml")
    with open(ledger, "rb") as fh:
        text = fh.read().decode("utf-8")
    assert "LOG-SYS-003" in text
    assert not any(line.strip() == "- LOG-001" for line in text.splitlines())
    # only the ledger and the capture's history files moved; items/ grew by
    # the append alone. W5b.5: the continuation save captures the predecessor
    # -- one `followed` event + its snapshot object, both under .refdes/history.
    after = tree(project_root, ".refdes")
    delta = set(after) - set(before_ledger)
    history_delta = {rel for rel in delta if rel.startswith(".refdes/history/")}
    assert delta - history_delta == {".refdes/ids.yaml"}
    assert sum(rel.startswith(".refdes/history/events/") for rel in history_delta) == 1
    assert sum(rel.startswith(".refdes/history/objects/") for rel in history_delta) == 1


def test_a_refused_operation_burns_no_id_and_the_next_save_reuses_the_number(
    project_root,
):
    """R5 (plan lines 390-393): a refusal lands nothing and reserves
    nothing -- create_item's commit-or-roll-back pairing, reused. The id the
    refusal would have taken is free for the next save."""
    before = tree(project_root, "items", ".refdes")

    refused = continue_thread(
        project_root, "LOG-SYS-002", [("T-nope", "done")], _tip_revision(project_root)
    )
    assert isinstance(refused, (Refused, Invalid)), refused
    assert tree(project_root, "items", ".refdes") == before  # no ids.yaml, no bytes

    result = continue_thread(
        project_root, "LOG-SYS-002", [("T-rail", "done")], _tip_revision(project_root)
    )
    assert isinstance(result, Applied), result.message
    assert result.item_id == "LOG-SYS-003"  # the number the refusal did not burn


# ------------------------------------------------------- hostile client payload


def test_hostile_follows_and_prefix_keys_in_the_ticks_are_refused(project_root):
    """Plan line 246 + R1: ticks are task rows, never field writes. A payload
    smuggling `follows:`/`prefix:` into the ticks names ids no row carries --
    refused as unknown ids; the composite the save writes is the server's
    (next test), and nothing client-named reaches the disk."""
    before = tree(project_root, "items", ".refdes")

    result = continue_thread(
        project_root,
        "LOG-SYS-002",
        [
            ("T-rail", "done"),
            ("follows", "LOG-SYS-999@deadbeefdeadbeef"),
            ("prefix", "EVIL"),
        ],
        _tip_revision(project_root),
    )
    _refused(result, "follows")
    assert tree(project_root, "items", ".refdes") == before
    text = _read_bytes(project_root, "items/log.yaml").decode("utf-8")
    assert "deadbeefdeadbeef" not in text and "EVIL" not in text


def test_the_follows_composite_is_the_servers_never_the_clients(project_root):
    """Plan line 246: `follows:` lands as the composite spelling
    `links.composite_for` produces for the tip -- a stale/hostile composite
    a client sends is not a field of the request at all, and the file shows
    the server's spelling for the tip the operation named."""
    tip = _load(project_root).item_by_id("LOG-SYS-002")
    composite = links.composite_for(tip)
    assert composite == f"LOG-SYS-002@{tip.key}"

    result = continue_thread(
        project_root, "LOG-SYS-002", [("T-rail", "done")], _tip_revision(project_root)
    )
    assert isinstance(result, Applied), result.message
    text = _read_bytes(project_root, "items/log.yaml").decode("utf-8")
    assert f"follows: [{composite}]" in text


# ------------------------------------------------------------------ the tip moved


def test_a_stale_revision_is_a_conflict_carrying_the_current_list_with_no_write(
    project_root,
):
    """The ratified Q3 default (a), implemented as W5b.1's revision compare
    (plan lines 484-485, 266-268): the tip moved under the draft -> Conflict
    with the current disk text (the current list is in it), nothing merged,
    nothing written."""
    stale = _tip_revision(project_root)
    # The tip moves: an ordinary editor save to the same file (a concurrent
    # author changing the summary) -- the file revision moves with it.
    applied = edit_mod.apply_edit(
        str(project_root),
        edit_mod.EditRequest(
            who="other-author",
            ref="LOG-SYS-002",
            op=edit_mod.SetField("summary", "Rail work, re-scoped."),
            expected_revision=stale,
        ),
    )
    assert isinstance(applied, Applied), applied.message

    result = continue_thread(
        project_root, "LOG-SYS-002", [("T-rail", "done")], stale
    )
    assert isinstance(result, Conflict), result.message
    assert result.ok is False
    assert result.expected_revision == stale
    assert result.current_revision == _tip_revision(project_root)
    assert result.current_text is not None
    # "Conflict with the current list": the carried text shows the rows as
    # disk has them now -- the ticked row is still open on disk.
    assert "T-rail" in result.current_text
    assert "Rail work, re-scoped." in _read_bytes(project_root, "items/log.yaml").decode("utf-8")
    # The conflict wrote nothing: the continuation landed nowhere.
    text = _read_bytes(project_root, "items/log.yaml").decode("utf-8")
    assert "LOG-SYS-003" not in text


# ------------------------------------------------------------------- concurrency


def test_two_simultaneous_continuations_land_one_and_conflict_the_other(project_root):
    """The write lock + revision compare: two authors tick the same tip
    against the same revision. Exactly one `Applied`; the loser is a
    `Conflict` (Q3's (a) -- refuse, never merge). The file carries ONE new
    entry (no double append), and exactly one id is reserved."""
    revision = _tip_revision(project_root)
    results: list = []
    barrier = threading.Barrier(2)

    def worker():
        barrier.wait(timeout=30)
        results.append(
            continue_thread(project_root, "LOG-SYS-002", [("T-rail", "done")], revision)
        )

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=120)
    assert len(results) == 2

    applied = [r for r in results if isinstance(r, Applied)]
    conflicted = [r for r in results if isinstance(r, Conflict)]
    assert len(applied) == 1, [type(r).__name__ for r in results]
    assert len(conflicted) == 1, [type(r).__name__ for r in results]

    text = _read_bytes(project_root, "items/log.yaml").decode("utf-8")
    assert text.count("- id: LOG-SYS-003") == 1  # one append, not two
    assert "LOG-SYS-004" not in text  # the loser reserved nothing
    ledger = os.path.join(str(project_root), ".refdes", "ids.yaml")
    with open(ledger, "rb") as fh:
        ledger_text = fh.read().decode("utf-8")
    assert "LOG-SYS-003" in ledger_text and "LOG-SYS-004" not in ledger_text


# ----------------------------------------------------------------- --no-write


def test_a_read_only_call_is_refused_naming_no_write_with_nothing_written(
    project_root,
):
    """The plan's W5b.1 gate (plan line 247): `--no-write` refuses. W5b.1
    has no HTTP face, so the flag travels on the operation (the sibling
    routes' refusal text names `--no-write`, `api.py:1168`/`:1372`); the
    tree is byte-identical."""
    before = tree(project_root, "items", ".refdes")

    result = continue_thread(
        project_root,
        "LOG-SYS-002",
        [("T-rail", "done")],
        _tip_revision(project_root),
        read_only=True,
    )
    assert isinstance(result, Refused), result.message
    assert "--no-write" in result.reason
    assert tree(project_root, "items", ".refdes") == before


# ---------------------------------------------------------- the delta gate (9)


def test_a_continuation_the_delta_gate_would_block_is_invalid_and_writes_nothing(
    tmp_path,
):
    """Plan line 233 (run the delta diagnostic gate, like apply_edit's step
    6, plan lines 31-37): a tip whose list carries a row outside the state
    vocabulary is already an error at the tip; copying that list verbatim
    introduces the SAME error attributed to the NEW entry, which the gate's
    before-set does not hold -- the candidate project would carry an error
    the gate blocks, so the save is Invalid and lands nothing."""
    write_project_config(tmp_path, SCHEMA)
    os.mkdir(os.path.join(str(tmp_path), "items"))
    _write(
        tmp_path,
        "items/log.yaml",
        "defaults: { type: log }\n"
        "items:\n"
        "  - {id: LOG-A, summary: Opens., date: 01/09/2026, tasks: "
        "[{id: T-a, text: A., state: open}, {id: T-b, text: B., state: closed}]}\n",
    )
    _mint_keys(tmp_path)
    project = _load(tmp_path)
    build_mod.build(project, seal_write=False, reseal=False)
    assert any("tasks" in d.message and "closed" in d.message for d in project.errors)
    before = tree(tmp_path, "items", ".refdes")

    result = continue_thread(
        tmp_path, "LOG-A", [("T-a", "done")], _tip_revision(tmp_path, "items/log.yaml")
    )
    assert isinstance(result, Invalid), f"expected the gate to block, got {result!r}"
    assert result.diagnostics
    assert any("closed" in d.message for d in result.diagnostics)
    assert tree(tmp_path, "items", ".refdes") == before


# ------------------------------------------------------------------ Q4: the tip


def test_an_older_entry_ref_continues_the_tip_not_that_entry(project_root):
    """The ratified Q4 (plan lines 491-499, §7a.1): the pane shows an older
    entry the tip's list; saving there continues the TIP. A ref naming
    LOG-SYS-001 writes a successor to LOG-SYS-002 -- the fold's tip -- with
    the tip's list, never a fork off the older entry."""
    tip_key = _load(project_root).item_by_id("LOG-SYS-002").key
    result = continue_thread(
        project_root, "LOG-SYS-001", [("T-rail", "done")], _tip_revision(project_root)
    )
    assert isinstance(result, Applied), result.message

    project = _load(project_root)
    new = project.item_by_id(result.item_id)
    assert new.links["follows"] == [f"LOG-SYS-002@{tip_key}"]
    # the thread stays a line: LOG-SYS-002 has exactly one successor (the
    # new entry), and the fold's single tip is the new entry with the
    # ticked list.
    tip_id, rows, _ambiguous = _fold_tip(project_root, result.item_id)
    assert tip_id == result.item_id
    assert rows[0] == {"id": "T-rail", "text": "Settle the rail budget.", "state": "done"}
