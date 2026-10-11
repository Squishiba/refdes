"""Living notes phase H7b: `refdes thread <ref>`.

docs/design/living-notes-plan.md §H7: the thread view of §6 as a command --
header, capture line, tip(s), tasks with age, derived block -- over the same
`threads_projection` the index payload carries ("a client must not
reconstruct the chain itself"). The binding rules are asserted as output
structure: two separately labelled groups with separate numbering (§5 rule 1:
derived rows carry no numbers at all), absolute ages without `--as-of` and
relative spans only under it (rule 3, pinned by a mocked clock), the folded
verdict printed with its tip's open tasks rather than alone (rule 4), and on
a fork one labelled block per open tip with no single current status line
anywhere.

The exit-code postures are the neighbours': an unknown ref or an entry on no
thread is a naming error (exit 2, like `history capture`'s item-not-in-the-
project row); a file that failed to parse is reported on stderr with the
answer intact and exit 1 (like `ls`).
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from unittest import mock

from conftest import write_project_config

from refdes import cli as cli_mod
from refdes import history

CONFIG = (
    "site: { title: Thread CLI, out: _site }\n"
    "standard: { base: hardware, version: 3 }\n"
)

ONE_TIP = (
    "defaults: { type: log }\n"
    "items:\n"
    "  - id: LOG-001\n"
    "    summary: Power work list.\n"
    "    date: 2026-08-30\n"
    "    tasks:\n"
    "      - {id: T-thermal-model, text: Model worst-case copper temperature., state: open}\n"
    "  - id: LOG-002\n"
    "    summary: Thermal modelling accepted.\n"
    "    date: 2026-09-02\n"
    "    follows: LOG-001\n"
    "    status: accepted\n"
)

FORK = (
    "defaults: { type: log }\n"
    "items:\n"
    "  - id: LOG-001\n"
    "    summary: Power work list.\n"
    "    date: 2026-08-30\n"
    "    tasks:\n"
    "      - {id: T-thermal-model, text: Model worst-case copper temperature., state: open}\n"
    "  - id: LOG-002\n"
    "    summary: Thermal branch.\n"
    "    date: 2026-09-02\n"
    "    follows: LOG-001\n"
    "    status: proposed\n"
    "  - id: LOG-003\n"
    "    summary: Decoupling branch.\n"
    "    date: 2026-09-03\n"
    "    follows: LOG-001\n"
    "    tasks:\n"
    "      - {id: T-decoupling, text: Recheck decoupling near U14., state: open}\n"
)

DERIVED = (
    "items:\n"
    "  - id: LOG-000\n"
    "    type: log\n"
    "    summary: Bring-up thread opens.\n"
    "    date: 2026-08-30\n"
    "  - id: LOG-001\n"
    "    type: log\n"
    "    summary: Board bring-up.\n"
    "    date: 2026-09-01\n"
    "    follows: LOG-000\n"
    "    tasks: [{id: t1, text: Measure idle current., state: open}]\n"
    "    addresses: REQ-001\n"
    "    citations: [{path: notes/datasheet.pdf}]\n"
    "  - id: REQ-001\n"
    "    type: requirement\n"
    "    title: Idle current budget\n"
    "    status: active\n"
    "    body: The idle rail must stay under 10 uA.\n"
)


def _setup(tmp_path, items_yaml=ONE_TIP, notes=False):
    write_project_config(tmp_path, CONFIG)
    items = tmp_path / "items"
    items.mkdir(exist_ok=True)
    (items / "log.yaml").write_text(items_yaml, encoding="utf-8")
    if notes:
        (tmp_path / "notes").mkdir(exist_ok=True)
        (tmp_path / "notes" / "datasheet.pdf").write_bytes(b"%PDF-1.4 fake\n")
    return str(tmp_path / "refdes-project.yaml")


def _run(config, *args):
    return cli_mod.main(["-c", config, *args])


def _fork_from_bare(tmp_path, capsys, config):
    """Make the bare two-siblings fixture an actual fork through the
    writable path's own rule (plan §H2: a bare `follows:` freezes to its
    target's *current tip*, so two siblings written bare in one file freeze
    into a chain). Warm once to mint the keys, then name LOG-001's key on
    the second sibling's edge -- the spelled-out frozen edge is how an
    author asks for a branch, and the freeze leaves an already-composite
    edge alone."""
    assert _run(config, "thread", "LOG-001") == 0
    capsys.readouterr()
    path = tmp_path / "items" / "log.yaml"
    text = path.read_text(encoding="utf-8")
    (root_key,) = re.findall(r"- key: (\S+)\n    id: LOG-001", text)
    # The warm run keyed every item, so entries start at `- key:` and the
    # id is the line after it; match the block by its id line, not by the
    # key line.
    blocks = re.split(r"(?=  - key: )", text)
    rebuilt = [
        re.sub(r"follows: LOG-002@\S+", f"follows: LOG-001@{root_key}", block)
        if re.match(r"  - key: \S+\n    id: LOG-003", block)
        else block
        for block in blocks
    ]
    text = "".join(rebuilt)
    assert f"follows: LOG-001@{root_key}" in text
    path.write_text(text, encoding="utf-8")
    assert _run(config, "thread", "LOG-001") == 0
    capsys.readouterr()


def _warm(tmp_path, config, capsys):
    """One writable run so every incidental write (keys, expansions, the
    follows capture) is already on disk: from here, the command's answer is
    the whole output -- no `(minted ... while loading)` line in front of it."""
    assert _run(config, "thread", "LOG-001") == 0
    capsys.readouterr()


def _tree(root):
    files = {}
    for dirpath, _dirnames, names in os.walk(str(root)):
        for name in names:
            path = os.path.join(dirpath, name)
            rel = os.path.relpath(path, str(root)).replace("\\", "/")
            with open(path, "rb") as fh:
                files[rel] = hashlib.sha256(fh.read()).hexdigest()
    return files


# ------------------------------------------------------------- the §6 view


def test_one_tip_thread_prints_the_sketched_view(tmp_path, capsys):
    """§6's sketch, honestly: header with the chain and the tip count, the
    capture line for the predecessor the writable load captured, the tip
    line, the concluding verdict printed *with* its open tasks (rule 4),
    the numbered authored tasks with their absolute declaring age (rule 3),
    and the labelled self-closing derived block."""
    config = _setup(tmp_path)
    _warm(tmp_path, config, capsys)
    assert _run(config, "thread", "LOG-002") == 0
    out = capsys.readouterr().out
    lines = out.splitlines()
    assert lines[0] == "Thread: LOG-001 -> LOG-002  (one tip)"
    # The followed edge carries no clock (H2), so no `at ...` -- the line
    # says captured and names the kind, and that is everything the store
    # actually knows.
    assert "Captured: LOG-001 (followed)" in lines
    assert "Tip: LOG-002  2026-09-02  Thermal modelling accepted." in lines
    # Rule 4's "never alone": the concluding verdict and the open-task
    # count print on one line, directly above the tasks themselves.
    assert any(
        line.startswith("Verdict: accepted (LOG-002, 2026-09-02)")
        and "concluding, 1 open task at this tip" in line
        for line in lines
    )
    assert lines.index("Tasks at tip:") < next(
        i for i, line in enumerate(lines) if line.startswith("Derived ")
    )
    task_line = next(line for line in lines if "T-thermal-model" in line)
    assert task_line == (
        "  1. [ ] T-thermal-model  Model worst-case copper temperature.  "
        "(open since LOG-001, 2026-08-30)"
    )
    assert "Derived (self-closing):" in lines
    assert "  (none)" in lines


def test_any_entry_on_the_thread_names_it(tmp_path, capsys):
    """The root works as well as the tip -- the argument is an entry, the
    answer is the thread."""
    config = _setup(tmp_path)
    _warm(tmp_path, config, capsys)
    assert _run(config, "thread", "LOG-001") == 0
    assert "Thread: LOG-001 -> LOG-002" in capsys.readouterr().out


def test_as_of_adds_relative_ages_and_without_it_there_are_none(tmp_path, capsys):
    """§5 rule 3, both halves: the declaring entry and date always print;
    the relative span exists only under an explicit --as-of."""
    config = _setup(tmp_path)
    _warm(tmp_path, config, capsys)
    assert _run(config, "thread", "LOG-001", "--as-of", "2026-09-02") == 0
    out = capsys.readouterr().out
    assert "(open since LOG-001, 2026-08-30 -- 3 days)" in out
    assert _run(config, "thread", "LOG-001") == 0
    assert " -- 3 days" not in capsys.readouterr().out


def test_output_does_not_depend_on_the_wall_clock(tmp_path, capsys):
    """The plan's reproducibility rule for the command itself: two runs with
    the clock two years apart print the same bytes (the age is `--as-of`'s
    or nobody's)."""
    config = _setup(tmp_path)
    _warm(tmp_path, config, capsys)
    assert _run(config, "thread", "LOG-001") == 0
    first = capsys.readouterr().out
    with mock.patch("time.time", return_value=1_700_000_000.0):
        assert _run(config, "thread", "LOG-001") == 0
    assert capsys.readouterr().out == first


def test_json_prints_the_projection_entry(tmp_path, capsys):
    """The machine-readable posture is cmd_index's json.dump: the thread's
    projection entry itself, which is exactly what the index payload
    carries under `threads` -- one answer, two doors."""
    config = _setup(tmp_path)
    _warm(tmp_path, config, capsys)
    assert _run(config, "thread", "LOG-002", "--json") == 0
    view = json.loads(capsys.readouterr().out)
    assert view["ref"] == "LOG-001"
    assert view["tips"] == ["LOG-002"]
    assert view["captured"] == [{"entry": "LOG-001", "kind": "followed", "occurred_at": None}]
    verdict = view["branches"][0]["verdict"]
    assert verdict["state"] == "declared"
    assert verdict["concluding"] is True


def test_as_of_and_json_refuse(tmp_path, capsys):
    """--as-of is a rendering option; --json is the clock-free projection.
    Saying nothing about one of them would be a silent option lie, so the
    combination exits 2 and says why."""
    config = _setup(tmp_path)
    assert _run(config, "thread", "LOG-001", "--json", "--as-of", "2026-09-02") == 2
    assert "--as-of" in capsys.readouterr().err


def test_bad_as_of_date_is_loud(tmp_path, capsys):
    config = _setup(tmp_path)
    assert _run(config, "thread", "LOG-001", "--as-of", "not-a-date") == 2
    assert "--as-of" in capsys.readouterr().err


# ------------------------------------------------------------------ the fork


def test_fork_prints_one_labelled_block_per_tip_and_no_global_status(
    tmp_path, capsys
):
    """§5 rule 4's fork half as output: the header names both tips, each
    branch prints its own labelled Tasks block, and no line asserts a
    single current status."""
    config = _setup(tmp_path, FORK)
    _fork_from_bare(tmp_path, capsys, config)
    assert _run(config, "thread", "LOG-001") == 0
    out = capsys.readouterr().out
    lines = out.splitlines()
    assert lines[0] == "Thread: LOG-001  (forked: tips LOG-002, LOG-003)"
    assert "Tasks at tip:" not in out
    assert "Tasks at LOG-002:" in lines
    assert "Tasks at LOG-003:" in lines
    # Branch-local verdicts: LOG-002's own `proposed`, LOG-003's silence
    # prints no Verdict line at all (a null verdict is not a status).
    assert any(line.startswith("Verdict: proposed") for line in lines)
    assert out.count("Verdict:") == 1
    # LOG-003's tip declares its own list; LOG-002 folds the head's.
    thermal = next(line for line in lines if "T-thermal-model" in line)
    decoupling = next(line for line in lines if "T-decoupling" in line)
    assert lines.index("Tasks at LOG-002:") < lines.index(thermal) < lines.index(
        "Tasks at LOG-003:"
    )
    assert lines.index("Tasks at LOG-003:") < lines.index(decoupling)


# ------------------------------------------------------- the fold's states


def test_task_block_states_print_as_themselves(tmp_path, capsys):
    """Each fold posture earns its own line rather than rendering as an
    empty list: reconciliation required (§5 rule 3), never declared, and
    cleared-by-nobody-who-declared."""
    text = (
        "defaults: { type: log }\n"
        "items:\n"
        "  - {id: LOG-001, summary: Left list., date: 2026-08-01, tasks: [{id: a, text: Left., state: open}]}\n"
        "  - {id: LOG-002, summary: Right list., date: 2026-08-02, tasks: [{id: b, text: Right., state: open}]}\n"
        "  - {id: LOG-003, summary: Silent merge., date: 2026-08-03, follows: [LOG-001, LOG-002]}\n"
        "  - {id: LOG-005, summary: Silent head., date: 2026-08-05}\n"
        "  - {id: LOG-006, summary: Silent continuation., date: 2026-08-06, follows: LOG-005}\n"
        "  - {id: LOG-007, summary: Cleared head., date: 2026-08-07, tasks: [{id: c, text: Closed., state: done}]}\n"
        "  - {id: LOG-008, summary: Cleared at tip., date: 2026-08-08, follows: LOG-007, tasks: []}\n"
    )
    config = _setup(tmp_path, text)
    _warm(tmp_path, config, capsys)
    assert _run(config, "thread", "LOG-003") == 0
    assert "task reconciliation required" in capsys.readouterr().out
    assert _run(config, "thread", "LOG-005") == 0
    assert "none (never declared)" in capsys.readouterr().out
    assert _run(config, "thread", "LOG-007") == 0
    assert "none (cleared by LOG-008)" in capsys.readouterr().out


def test_ambiguous_verdict_prints_as_itself(tmp_path, capsys):
    """H7b review fix (a) as output: a refused fold says so rather than
    rendering as if nothing had concluded."""
    text = (
        "defaults: { type: log }\n"
        "items:\n"
        "  - {id: LOG-001, summary: Accepted parent., date: 2026-08-01, status: accepted}\n"
        "  - {id: LOG-002, summary: Held parent., date: 2026-08-02, status: proposed}\n"
        "  - {id: LOG-003, summary: Silent merge., date: 2026-08-03, follows: [LOG-001, LOG-002]}\n"
    )
    config = _setup(tmp_path, text)
    _warm(tmp_path, config, capsys)
    assert _run(config, "thread", "LOG-001") == 0
    out = capsys.readouterr().out
    assert "Verdict: ambiguous" in out
    assert "Verdict: accepted" not in out


def test_derived_block_reads_like_problems_not_tasks(tmp_path, capsys):
    """§5 rule 1's separation on the terminal: derived rows carry no
    checkbox, no number, and the worklist's own vocabulary, while the
    authored rows keep theirs."""
    config = _setup(tmp_path, DERIVED, notes=True)
    _warm(tmp_path, config, capsys)
    assert _run(config, "thread", "LOG-001") == 0
    lines = capsys.readouterr().out.splitlines()
    start = lines.index("Derived (self-closing):")
    rows = lines[start + 1 :]
    assert any(line.strip().startswith("coverage  REQ-001  unverified") for line in rows)
    assert any(line.strip().startswith("citation  LOG-001  unpinned") for line in rows)
    assert not any("[" in line for line in rows)  # no checkbox renders a derived row
    assert not any(line.lstrip()[:2].rstrip(".").isdigit() for line in rows)


def test_capture_line_names_the_time_the_store_records(tmp_path, capsys):
    """The explicit `history capture` is the one event that may carry a
    clock (§2/H4), and the capture line prints it when it does."""
    config = _setup(tmp_path)
    _warm(tmp_path, config, capsys)
    from refdes import loader

    loaded, _ = loader.load_tree(config)
    result = history.capture(
        str(tmp_path), loaded.item_by_id("LOG-002"), occurred_at="2026-09-15T14:08:00Z"
    )
    assert result.created_event
    assert _run(config, "thread", "LOG-002") == 0
    out = capsys.readouterr().out
    assert "Captured: LOG-002 at 2026-09-15T14:08:00Z (captured)" in out
    assert "Captured: LOG-001 (followed)" in out


# ---------------------------------------------------------------- exit codes


def test_unknown_ref_is_a_clear_error(tmp_path, capsys):
    config = _setup(tmp_path)
    _warm(tmp_path, config, capsys)
    assert _run(config, "thread", "LOG-999") == 2
    err = capsys.readouterr().err
    assert "no item 'LOG-999' in this project" in err
    assert "looked up by display id, then surrogate key" in err


def test_entry_on_no_thread_is_a_clear_error(tmp_path, capsys):
    config = _setup(tmp_path, ONE_TIP + "  - {id: LOG-009, summary: Solo note., date: 2026-09-09}\n")
    _warm(tmp_path, config, capsys)
    assert _run(config, "thread", "LOG-009") == 2
    err = capsys.readouterr().err
    assert "not part of a thread" in err
    assert "no follows: edge either way" in err


def test_unparsable_file_is_reported_with_the_answer_intact(tmp_path, capsys):
    """cmd_ls's posture: the parse error goes to stderr and the exit is 1,
    but the thread that *did* load still prints its answer (it may simply
    be missing an entry -- the stderr line says so)."""
    config = _setup(tmp_path)
    _warm(tmp_path, config, capsys)
    (tmp_path / "items" / "broken.yaml").write_text("items: [\n", encoding="utf-8")
    assert _run(config, "thread", "LOG-002") == 1
    captured = capsys.readouterr()
    assert "Thread: LOG-001 -> LOG-002" in captured.out
    assert captured.err.strip()


# ------------------------------------------------------------------- writes


def test_no_write_run_writes_nothing(tmp_path, capsys):
    """The plan's tree-hash test for the command, through `--no-write` so a
    dirty tree (pending keys, pending expansions) proves the point: the
    thread's own work opens the store read-only and builds with
    `seal_write=False`."""
    config = _setup(tmp_path)
    # Warm writable first so the store/keys exist, then snapshot.
    assert _run(config, "thread", "LOG-001") == 0
    capsys.readouterr()
    before = _tree(tmp_path)
    assert _run(config, "--no-write", "thread", "LOG-001") == 0
    assert _tree(tmp_path) == before


def test_the_command_itself_never_seals(tmp_path, capsys):
    """`seal_write=False` like `index`/`ls`: a plain writable run of the
    standard project (whose `log` type is append-only and sealed) still
    leaves no seal record behind -- the only files a `thread` run may add
    are the load's incidental ones, never a sealing write."""
    config = _setup(tmp_path)
    assert _run(config, "thread", "LOG-001") == 0
    capsys.readouterr()
    sealed = [p for p in _tree(tmp_path) if "seal" in p]
    assert sealed == []


def test_derived_row_self_closes_after_a_real_fix(tmp_path, capsys):
    """§5 rule 2 end-to-end through the command: the `coverage REQ-001
    unverified` row disappears when the requirement actually gets verified
    -- and the authors' task block is byte-identical across the fix, so
    nothing was ticked or written back, the gap just closed."""
    config = _setup(tmp_path, DERIVED, notes=True)
    _warm(tmp_path, config, capsys)
    assert _run(config, "thread", "LOG-001") == 0
    before = capsys.readouterr().out
    assert "coverage  REQ-001  unverified" in before

    (tmp_path / "items" / "test.yaml").write_text(
        "items:\n"
        "  - id: TST-001\n"
        "    type: test\n"
        "    title: Idle current measured\n"
        "    status: passing\n"
        "    verifies: REQ-001\n",
        encoding="utf-8",
    )
    assert _run(config, "thread", "LOG-001") == 0
    after = capsys.readouterr().out
    assert "coverage  REQ-001  unverified" not in after
    task = next(line for line in before.splitlines() if "t1" in line)
    assert task in after.splitlines()
