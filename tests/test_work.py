"""Living notes phase H7c: `refdes work` (the project-wide worklist).

docs/design/living-notes-plan.md §H7 and living-notes.md §5's "Generated
worklist" + "Binding rules for the worklist", read as output *structure*: the
authored tasks and the derived rows are two separately labelled groups with
separate numbering (derived rows carry no number and no checkbox, self-close,
and are never written back), every open task prints its declaring entry and
date, relative spans appear only under `--as-of` (so the bytes never depend on
the wall clock), a concluding verdict prints with its tip's open tasks rather
than alone, and a fork prints one block per tip with no single current status.

The thread half is the same `threads_projection` `refdes thread` renders and
the index carries; the derived half is `threads.project_derived` over the whole
project. The command itself computes no fold, coverage stage, or check, reads
no clock, and writes nothing but the load's own key minting/expansions.

Exit-code postures are the neighbours': a read/list command exits 0 whatever
the worklist contains (it is not a gate -- H8 is); a file that failed to parse
is reported on stderr with the listing intact and exit 1 (like `ls`/`thread`).
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from unittest import mock

import pytest

from conftest import write_project_config

from refdes import cli as cli_mod
from refdes import loader

CONFIG = (
    "site: { title: Work, out: _site }\n"
    "standard: { base: hardware, version: 3 }\n"
)

# The authored thread: one tip whose verdict concludes while a task stays open
# (rule 4), a done task too (so numbering of the open subset is visible), and
# deliberately no derived gap of its own.
AUTHORED = (
    "defaults: { type: log }\n"
    "items:\n"
    "  - id: LOG-001\n"
    "    summary: Power work list.\n"
    "    date: 2026-08-30\n"
    "    tasks:\n"
    "      - {id: T-thermal-model, text: Model worst-case copper temperature., state: open}\n"
    "      - {id: T-input-range, text: Check the 36 V input case., state: done}\n"
    "  - id: LOG-002\n"
    "    summary: Thermal modelling accepted.\n"
    "    date: 2026-09-02\n"
    "    follows: LOG-001\n"
    "    status: accepted\n"
)

# The gaps, all in one file that is NOT the authored-task file, so any fix here
# (or in a brand-new file / the lockfile) leaves the authored task file's bytes
# untouched -- the read_bytes comparison that proves nothing was ticked or
# written back. Covers five of the six offline row kinds; the fork lives in its
# own fixture (it needs the writable path's anchor dance to be a real fork).
GAPS = (
    "items:\n"
    "  - id: REQ-001\n"
    "    type: requirement\n"
    "    title: Idle current budget\n"
    "    status: active\n"
    "    body: The idle rail must stay under 10 uA.\n"
    "  - id: BND-001\n"
    "    type: bound\n"
    "    title: Idle power\n"
    "    status: active\n"
    "    limit: <= 0.5 W\n"
    "    body: The board may not burn more than half a watt idle.\n"
    "  - id: LOG-010\n"
    "    type: log\n"
    "    summary: Power budget attempt.\n"
    "    date: 2026-09-01\n"
    "    checks: [{value: P_diss, against: BND-001}]\n"
    "    body: |\n"
    "      ```calc\n"
    "      P_diss = 2 W\n"
    "      ```\n"
    "  - id: CMP-001\n"
    "    type: component\n"
    "    title: LDO regulator\n"
    "    status: candidate\n"
    "  - id: LOG-011\n"
    "    type: log\n"
    "    summary: Blocked work.\n"
    "    date: 2026-09-01\n"
    "    blocked_by: CMP-001\n"
    "  - id: LOG-012\n"
    "    type: log\n"
    "    summary: Needs a pin.\n"
    "    date: 2026-09-01\n"
    "    citations: [{path: notes/datasheet.pdf}]\n"
    "  - id: LOG-020\n"
    "    type: log\n"
    "    summary: Verdict thread head.\n"
    "    date: 2026-08-30\n"
    "  - id: LOG-021\n"
    "    type: log\n"
    "    summary: Proposed verdict, nobody has concluded it.\n"
    "    date: 2026-09-01\n"
    "    follows: LOG-020\n"
    "    status: proposed\n"
)

# A thread whose tip is proposed (a non-concluding verdict: a derived row, and
# its tip carries no open task so it prints no authored block).
PROPOSED = (
    "defaults: { type: log }\n"
    "items:\n"
    "  - {id: LOG-030, summary: Decision pending head., date: 2026-08-30}\n"
    "  - {id: LOG-031, summary: Proposed decision., date: 2026-09-01, follows: LOG-030, status: proposed}\n"
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

# The same fork shape, but LOG-002's tip has declared its own list and
# settled it: the tip has NO open task. `refdes work` (the worklist) hides
# that tip's Tasks block; `refdes thread` still prints it (owner decision,
# 2026-10-11 -- answer to the worklist's question 4).
FORK_SETTLED_TIP = (
    "defaults: { type: log }\n"
    "items:\n"
    "  - id: LOG-001\n"
    "    summary: Power work list.\n"
    "    date: 2026-08-30\n"
    "  - id: LOG-002\n"
    "    summary: Thermal branch, nothing left open.\n"
    "    date: 2026-09-02\n"
    "    follows: LOG-001\n"
    "    tasks: [{id: T-old, text: Old settled thing., state: done}]\n"
    "  - id: LOG-003\n"
    "    summary: Decoupling branch.\n"
    "    date: 2026-09-03\n"
    "    follows: LOG-001\n"
    "    tasks:\n"
    "      - {id: T-decoupling, text: Recheck decoupling near U14., state: open}\n"
)

# A MERGE: two entries at the same distance from the shared tip declare
# different statuses (LOG-007 `accepted`, LOG-008 `proposed`), so the fold of
# `status` at LOG-009 REFUSED (state `conflicting`). Nothing anywhere carries
# an open task -- review #194 W5 found a refused fold like this vanished from
# `refdes work` entirely (the authored blocks skip tips with no open task, and
# the derived `verdict` row used to enumerate only proposed/on_hold).
MERGE_CONFLICT = (
    "defaults: { type: log }\n"
    "items:\n"
    "  - {id: LOG-007, summary: Settled left., date: 2026-08-07, status: accepted}\n"
    "  - {id: LOG-008, summary: Held right., date: 2026-08-08, status: proposed}\n"
    "  - {id: LOG-009, summary: Silent merge., date: 2026-08-09, follows: [LOG-007, LOG-008]}\n"
)

# The same merge shape again, but now the two folds refuse DIFFERENTLY: the
# parents declare the SAME status (so the status fold RESOLVES to the
# concluding `accepted`) while their task lists differ (so the task fold
# REFUSES). The folds are independent (`threads._thread_view` computes them
# separately); a concluding fold earns no derived row, and review #194 R1
# found this verdict vanishing from `refdes work` -- the ambiguous-task
# branch `continue`d before the verdict check.
MERGE_AMBIGUOUS_CONCLUDED = (
    "defaults: { type: log }\n"
    "items:\n"
    "  - {id: LOG-007, summary: Left list., date: 2026-08-07, status: accepted,"
    " tasks: [{id: t-left, text: Left thing., state: open}]}\n"
    "  - {id: LOG-008, summary: Right list., date: 2026-08-08, status: accepted,"
    " tasks: [{id: t-right, text: Right thing., state: open}]}\n"
    "  - {id: LOG-009, summary: Accepted merge., date: 2026-08-09,"
    " follows: [LOG-007, LOG-008]}\n"
)

# The same merge, but the shared tip carries an open task: rule 4's authored
# pairing (`Verdict: conflicting -- ...` printed WITH the open tasks) is
# review #194 W3's wiring, previously untested on this command.
MERGE_CONFLICT_OPEN = (
    "defaults: { type: log }\n"
    "items:\n"
    "  - {id: LOG-007, summary: Settled left., date: 2026-08-07, status: accepted}\n"
    "  - {id: LOG-008, summary: Held right., date: 2026-08-08, status: proposed}\n"
    "  - id: LOG-009\n"
    "    summary: Silent merge with open work.\n"
    "    date: 2026-08-09\n"
    "    follows: [LOG-007, LOG-008]\n"
    "    tasks: [{id: t1, text: Reconcile the two parents., state: open}]\n"
)


def _setup(tmp_path, *files):
    write_project_config(tmp_path, CONFIG)
    items = tmp_path / "items"
    items.mkdir(exist_ok=True)
    for name, text in files:
        (items / name).write_text(text, encoding="utf-8")
    (tmp_path / "notes").mkdir(exist_ok=True)
    (tmp_path / "notes" / "datasheet.pdf").write_bytes(b"%PDF-1.4 fake\n")
    return str(tmp_path / "refdes-project.yaml")


def _authored(tmp_path):
    return _setup(tmp_path, ("thread.yaml", AUTHORED))


def _gaps(tmp_path):
    return _setup(tmp_path, ("thread.yaml", AUTHORED), ("gaps.yaml", GAPS))


def _run(config, *args):
    return cli_mod.main(["-c", config, *args])


def _tree(root):
    files = {}
    for dirpath, _dirnames, names in os.walk(str(root)):
        for name in names:
            path = os.path.join(dirpath, name)
            rel = os.path.relpath(path, str(root)).replace("\\", "/")
            with open(path, "rb") as fh:
                files[rel] = hashlib.sha256(fh.read()).hexdigest()
    return files


def _derived_rows(out: str) -> list[str]:
    lines = out.splitlines()
    start = lines.index(cli_mod.THREAD_DERIVED_HEADING)
    return lines[start + 1 :]


def _derived_groups(out: str) -> dict[str, list[str]]:
    """The derived block read back through the owner's grouped shape (2026-10-11):
    {kind: [row, ...]} keyed by the row kind, parsed through the shared heading
    words themselves (so the test reads the shape, never re-spells a heading),
    insertion-ordered as printed. `(none)` reads back as no groups at all. A
    group's rows keep their `ref  detail` text, without the kind column."""
    lines = out.splitlines()
    start = lines.index(cli_mod.THREAD_DERIVED_HEADING)
    words = {
        heading: kind for kind, heading in cli_mod.THREAD_DERIVED_GROUP_HEADINGS.items()
    }
    groups: dict[str, list[str]] = {}
    current: str | None = None
    for line in lines[start + 1 :]:
        if line.strip() == "(none)":
            return {}
        if line.startswith("    ") and current is not None:
            groups[current].append(line.strip())
        elif line.startswith("  ") and not line.startswith("    "):
            word = line.strip()
            assert word.endswith(":"), f"not a group heading: {word!r}"
            current = words[word[:-1]]
            groups[current] = []
    return groups


def _warm(tmp_path, config, capsys):
    """One writable run so keys are minted and edges anchored on disk; from here
    the answer is the whole output (no `(minted ... while loading)` line in
    front of it)."""
    assert _run(config, "work") == 0
    capsys.readouterr()


def _fork_from_bare(tmp_path, config, capsys):
    """Bare siblings anchor into a chain on the first writable load (plan §H2);
    an author asks for a real branch by naming the target's key. Warm once to
    mint keys, then rewrite the younger sibling's anchored edge back onto the
    root's key -- the same dance tests/test_thread_cli.py uses."""
    assert _run(config, "work") == 0
    capsys.readouterr()
    path = tmp_path / "items" / "log.yaml"
    text = path.read_text(encoding="utf-8")
    (root_key,) = re.findall(r"- key: (\S+)\n    id: LOG-001", text)
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


# -------------------------------------------------- two groups, separate numbering


def test_authored_and_derived_are_separate_groups_with_separate_numbering(tmp_path, capsys):
    """§5 rule 1: the two groups print under their own labels, numbered
    independently -- the authored tasks get the `1. [ ] ...` rows with their
    declaring age (rule 3), the derived rows get no number and no checkbox."""
    config = _gaps(tmp_path)
    _warm(tmp_path, config, capsys)
    assert _run(config, "work") == 0
    out = capsys.readouterr().out
    lines = out.splitlines()
    assert lines[0] == "Worklist:"
    assert "Tasks at tip:" in lines
    task = next(line for line in lines if "T-thermal-model" in line)
    # Only the open task is listed, and it numbers from 1; the done sibling is
    # not work and does not shift it.
    assert task == "  1. [ ] T-thermal-model  Model worst-case copper temperature.  (open since LOG-001, 2026-08-30)"
    assert "T-input-range" not in out  # a done task is not on the worklist
    # The derived block is a separate labelled group, below the authored one.
    assert lines.index("Tasks at tip:") < lines.index(cli_mod.THREAD_DERIVED_HEADING)
    rows = _derived_rows(out)
    assert rows  # the gaps fixture really has gaps
    assert not any("[" in row for row in rows)  # no checkbox renders a derived row
    assert not any(row.lstrip()[:2].rstrip(".").isdigit() for row in rows)  # no numbers


def test_an_explicit_null_id_or_text_prints_placeholder_not_the_word_none(
    tmp_path, capsys
):
    """PR #191 review nit: a task row written `id:`/`text:` with an explicit
    null (shape validation owns that error, and the fold keeps the dict) used
    to render the literal "None" through `row.get('id', '?')` -- `get`'s
    default only covers the *missing* key. The row renders `?`/empty instead,
    and the listing stays intact (shared `_task_row_lines`, so `refdes thread`
    reads the same row the same way)."""
    text = (
        "defaults: { type: log }\n"
        "items:\n"
        "  - {id: LOG-001, summary: Head., date: 2026-08-30}\n"
        "  - {id: LOG-002, summary: Null-row tip., date: 2026-09-01, follows: LOG-001, tasks: [{id: null, text: null, state: open}]}\n"
    )
    config = _setup(tmp_path, ("nullrow.yaml", text))
    _warm(tmp_path, config, capsys)
    assert _run(config, "work") == 0
    out = capsys.readouterr().out
    assert "None" not in out
    row = next(line for line in out.splitlines() if line.startswith("  1. [ ]"))
    assert row.startswith("  1. [ ] ?  ")  # `?` for the null id, empty text


def test_an_explicit_empty_string_id_prints_the_placeholder_too():
    """Review #194 R2 (nit): `or` reads an explicit empty-string id as falsy
    too -- the intended reading (a row with no usable id prints `?`), pinned
    directly on the shared row builder both commands render through."""
    rows = [{"id": "", "text": "Still renders.", "state": "done"}]
    assert cli_mod._task_row_lines(rows, None, "%Y-%m-%d") == ["  1. [x] ?  Still renders."]


def test_concluding_verdict_prints_with_its_open_tasks(tmp_path, capsys):
    """§5 rule 4, the worklist half: the tip's `accepted` verdict is concluding
    while a task is still open, so the verdict prints directly above that tip's
    open tasks and says so -- never a verdict alone."""
    config = _authored(tmp_path)
    _warm(tmp_path, config, capsys)
    assert _run(config, "work") == 0
    lines = capsys.readouterr().out.splitlines()
    verdict = next(line for line in lines if line.startswith("Verdict: accepted"))
    assert "1 open task remaining below" in verdict
    assert verdict == (
        "Verdict: accepted (LOG-002, 2026-09-02), 1 open task remaining below"
    )
    assert lines.index(verdict) < next(i for i, line in enumerate(lines) if "T-thermal-model" in line)


# -------------------------------------------------------- the derived row kinds


def test_every_offline_derived_kind_appears_in_table_order(tmp_path, capsys):
    """§5's table lists the row kinds; five of the six offline kinds come from a
    gap in a project file that carries no authored task at all (project-level
    rows still surface -- they are the project's gaps, not some thread's). The
    block is ordered coverage < verdict < blocked < check < citation, the
    table's own order."""
    config = _gaps(tmp_path)
    _warm(tmp_path, config, capsys)
    assert _run(config, "work") == 0
    out = capsys.readouterr().out
    groups = _derived_groups(out)
    # Owner decision 2026-10-11: one heading per kind that has rows, in the
    # ONE shared order (threads._KIND_ORDER -- the §5 table's order), rows
    # within a kind by ref, no kind column inside a group.
    order = ["coverage", "verdict", "blocked", "check", "citation", "fork"]
    assert list(groups) == [kind for kind in order if kind in groups]
    assert set(groups) == {"coverage", "verdict", "blocked", "check", "citation"}
    assert groups["coverage"] == ["BND-001  uncovered", "REQ-001  uncovered"]
    assert groups["verdict"] == ["LOG-021  proposed"]
    assert groups["blocked"] == ["LOG-011  by CMP-001 (candidate)"]
    assert groups["check"] == ["LOG-010  P_diss violates BND-001"]
    assert groups["citation"] == ["LOG-012  unpinned"]


def test_an_unknown_derived_kind_is_named_not_a_bare_keyerror():
    """Review #194 W6: `threads.py` is free to grow a derived kind, and the
    renderer must then be taught it -- but until it is, the failure must name
    the unknown kind rather than die on a bare KeyError three frames away.
    Both halves of the rendering (the group-heading lookup and the detail
    dispatch) must say so."""
    row = {"kind": "widget", "ref": "WDG-001"}
    with pytest.raises(ValueError, match="widget"):
        cli_mod._derived_lines([row])
    with pytest.raises(ValueError, match="widget"):
        cli_mod._derived_detail(row)


# ------------------------------------------------------------------- the fork


def test_fork_prints_every_tip_with_its_own_block_and_no_single_status(tmp_path, capsys):
    """§5 rule 5 as output: a forked thread's two tips each get their own
    labelled `Tasks at <tip>:` block, the header names both tips, there is no
    `Tasks at tip:` (there is no single tip), and no line anywhere asserts a
    single current status -- the fork itself is a derived row instead."""
    config = _setup(tmp_path, ("log.yaml", FORK))
    _fork_from_bare(tmp_path, config, capsys)
    assert _run(config, "work") == 0
    out = capsys.readouterr().out
    lines = out.splitlines()
    assert "Thread: LOG-001  (forked: tips LOG-002, LOG-003)" in lines
    assert "Tasks at tip:" not in out
    assert "Tasks at LOG-002:" in lines
    assert "Tasks at LOG-003:" in lines
    thermal = next(line for line in lines if "T-thermal-model" in line)
    decoupling = next(line for line in lines if "T-decoupling" in line)
    assert lines.index("Tasks at LOG-002:") < lines.index(thermal) < lines.index("Tasks at LOG-003:")
    assert lines.index("Tasks at LOG-003:") < lines.index(decoupling)
    # The LOG-002 tip's `proposed` verdict is a derived row (an open decision),
    # not a Verdict line attached to the authored block, and the fork is a row.
    groups = _derived_groups(out)
    assert groups["verdict"] == ["LOG-002  proposed"]
    assert groups["fork"] == ["LOG-001  tips LOG-002, LOG-003"]
    # No thread-level status line for a fork.
    assert not any(line.startswith("Verdict:") for line in lines)


def test_work_hides_a_fork_tip_with_no_open_task(tmp_path, capsys):
    """Owner decision 2026-10-11 (worklist question 4): a worklist of open
    work prints no empty `Tasks at <tip>:` block -- a fork tip whose own
    list is settled contributes nothing to the authored group. Nothing is
    lost by the omission: the forked header names every tip and the derived
    `fork` row still names the same tips."""
    config = _setup(tmp_path, ("log.yaml", FORK_SETTLED_TIP))
    _fork_from_bare(tmp_path, config, capsys)
    assert _run(config, "work") == 0
    out = capsys.readouterr().out
    lines = out.splitlines()
    assert "Thread: LOG-001  (forked: tips LOG-002, LOG-003)" in lines
    assert "Tasks at LOG-003:" in lines  # the tip that has the open task
    assert "Tasks at LOG-002:" not in lines  # the settled tip: no empty block
    assert "T-old" not in out
    assert _derived_groups(out)["fork"] == ["LOG-001  tips LOG-002, LOG-003"]


def test_thread_still_prints_a_fork_tip_with_no_open_task(tmp_path, capsys):
    """The other half of the same decision: the hide belongs to the
    WORKLIST only. `refdes thread` is the single thread's view, not a
    listing of open work, and it still prints every tip's block -- here
    the settled tip's own list (the done row), not an empty block."""
    config = _setup(tmp_path, ("log.yaml", FORK_SETTLED_TIP))
    _fork_from_bare(tmp_path, config, capsys)
    assert _run(config, "thread", "LOG-001") == 0
    lines = capsys.readouterr().out.splitlines()
    assert "Tasks at LOG-002:" in lines
    assert "Tasks at LOG-003:" in lines
    assert any(line.strip().startswith("1. [x] T-old") for line in lines)
    assert any(line.strip().startswith("1. [ ] T-decoupling") for line in lines)


# -------------------------------------------------------------- derived self-close


def test_derived_rows_self_close_without_writing_anything_back(tmp_path, capsys):
    """§5 rule 2 end-to-end through the command: closing the coverage gap (a
    real passing test that verifies REQ-001) removes exactly the REQ-001
    coverage row -- the other gaps stay -- while the authored task file is
    byte-identical and still lists the same open task. Nothing was ticked, no
    'done' recorded, nothing written back: the gap just closed."""
    config = _gaps(tmp_path)
    _warm(tmp_path, config, capsys)
    task_file = tmp_path / "items" / "thread.yaml"
    task_bytes_before = task_file.read_bytes()
    assert _run(config, "work") == 0
    before = _derived_groups(capsys.readouterr().out)
    assert "REQ-001  uncovered" in before["coverage"]
    assert "BND-001  uncovered" in before["coverage"]

    (tmp_path / "items" / "test.yaml").write_text(
        "items:\n"
        "  - id: TST-001\n"
        "    type: test\n"
        "    title: Idle current measured\n"
        "    status: passing\n"
        "    verifies: REQ-001\n",
        encoding="utf-8",
    )
    assert _run(config, "work") == 0
    after = _derived_groups(capsys.readouterr().out)
    assert "REQ-001  uncovered" not in after.get("coverage", [])
    assert "BND-001  uncovered" in after["coverage"]  # other gaps stay
    # The authored tasks were never touched: same bytes on disk, same open task
    # on screen -- the derived row closed itself, it was not ticked.
    assert task_file.read_bytes() == task_bytes_before
    assert _run(config, "work") == 0
    assert "T-thermal-model  Model worst-case copper temperature." in capsys.readouterr().out


def test_citation_row_self_closes_by_pinning_the_document(tmp_path, capsys):
    """A different remedy clears a different kind: pinning the local citation
    (`refdes fetch` writes the lockfile, not the source) removes the citation
    row -- and the gaps file's bytes are untouched, so no write-back."""
    config = _gaps(tmp_path)
    _warm(tmp_path, config, capsys)
    gaps_file = tmp_path / "items" / "gaps.yaml"
    gaps_bytes = gaps_file.read_bytes()
    assert _run(config, "work") == 0
    assert "LOG-012  unpinned" in _derived_groups(capsys.readouterr().out)["citation"]

    assert _run(config, "fetch") == 0
    capsys.readouterr()
    assert _run(config, "work") == 0
    assert "citation" not in _derived_groups(capsys.readouterr().out)
    assert gaps_file.read_bytes() == gaps_bytes


def test_verdict_row_self_closes_when_the_decision_is_made(tmp_path, capsys):
    """A proposed verdict is a derived row while it waits; concluding it (the
    author's own edit to the thread, not a worklist tick) removes the row."""
    config = _setup(tmp_path, ("thread.yaml", PROPOSED))
    _warm(tmp_path, config, capsys)
    assert _run(config, "work") == 0
    assert _derived_groups(capsys.readouterr().out)["verdict"] == ["LOG-031  proposed"]

    log = tmp_path / "items" / "thread.yaml"
    log.write_text(
        log.read_text(encoding="utf-8").replace("status: proposed", "status: accepted"),
        encoding="utf-8",
    )
    assert _run(config, "work") == 0
    assert "verdict" not in _derived_groups(capsys.readouterr().out)


def test_a_refused_verdict_fold_is_a_derived_row_even_with_no_open_task(tmp_path, capsys):
    """Review #194 W5: the authored blocks skip every tip with no open task
    (owner decision 4) and the derived `verdict` row used to enumerate only
    proposed/on_hold — so a fold that REFUSED (§5 rule 3: entries at the same
    distance declaring different statuses) at a taskless tip vanished from
    `refdes work` entirely. Something that needs reconciling must always be
    on the worklist: it lists in the existing Verdicts group, as the
    projection's own state word, once per tip (both merged threads fold the
    same verdict at the same tip)."""
    config = _setup(tmp_path, ("log.yaml", MERGE_CONFLICT))
    _warm(tmp_path, config, capsys)
    assert _run(config, "work") == 0
    out = capsys.readouterr().out
    assert "  (no open tasks authored)" in out.splitlines()  # nothing authored anywhere...
    assert _derived_groups(out)["verdict"] == ["LOG-009  conflicting"]  # ...yet the conflict is listed, once


def test_a_refused_verdict_fold_prints_with_its_tip_s_open_tasks_too(tmp_path, capsys):
    """Rule 4's authored pairing on this command (review #194 W3, the
    `VERDICT_CONFLICTING` clause in `_work_authored_blocks`): when the merged
    tip carries an open task, the refusal prints directly above it — main's
    owner-worded sentence through the shared `_verdict_line`, re-spelled
    nowhere — and the derived guarantee (the test above) holds alongside."""
    config = _setup(tmp_path, ("log.yaml", MERGE_CONFLICT_OPEN))
    _warm(tmp_path, config, capsys)
    assert _run(config, "work") == 0
    lines = capsys.readouterr().out.splitlines()
    verdict_at = lines.index(
        "Verdict: conflicting -- entries at the same distance declare "
        "different statuses; a continuation must declare one explicitly"
    )
    task_at = next(i for i, line in enumerate(lines) if "Reconcile the two parents." in line)
    assert verdict_at < task_at  # the verdict never stands alone
    assert _derived_groups("\n".join(lines))["verdict"] == ["LOG-009  conflicting"]


def test_an_ambiguous_task_fold_does_not_swallow_a_concluding_verdict(tmp_path, capsys):
    """Review #194 R1: the task fold and the status fold are independent, so
    a tip can carry a REFUSED task list and a resolved CONCLUDING status at
    once. A concluding fold earns no derived row (rule 4 pairs it with the
    tip's block instead), and `refdes work` used to `continue` on the
    ambiguous list before the verdict check -- the verdict then vanished from
    the command entirely. The verdict line now prints there too, the exact
    line `refdes thread` prints (the shared `_verdict_line`), above the
    reconciliation line."""
    config = _setup(tmp_path, ("log.yaml", MERGE_AMBIGUOUS_CONCLUDED))
    _warm(tmp_path, config, capsys)
    assert _run(config, "work") == 0
    lines = capsys.readouterr().out.splitlines()
    verdict_at = next(i for i, line in enumerate(lines) if line.startswith("Verdict: accepted"))
    reconciliation_at = lines.index("Tasks at tip: task reconciliation required")
    assert verdict_at < reconciliation_at  # the verdict never stands alone
    assert _run(config, "thread", "LOG-009") == 0  # the same line, spelled once
    assert lines[verdict_at] in capsys.readouterr().out.splitlines()


def test_an_on_hold_verdict_is_listed_like_a_proposed_one(tmp_path, capsys):
    """Review #194 W8: `_OPEN_VERDICTS`' second member had no test anywhere —
    dropping `on_hold` from the filter broke nothing. §5's table row names
    both values: a decision someone is deliberately holding is exactly the
    "still has to decide" gap, and it lists in the same Verdicts group with
    its own status word."""
    text = (
        "defaults: { type: log }\n"
        "items:\n"
        "  - {id: LOG-040, summary: Decision head., date: 2026-08-30}\n"
        "  - {id: LOG-041, summary: Decision held., date: 2026-09-01, follows: LOG-040, status: on_hold}\n"
    )
    config = _setup(tmp_path, ("log.yaml", text))
    _warm(tmp_path, config, capsys)
    assert _run(config, "work") == 0
    assert _derived_groups(capsys.readouterr().out)["verdict"] == ["LOG-041  on_hold"]


def test_a_concluding_on_hold_never_becomes_a_lone_worklist_row(tmp_path, capsys):
    """Review #194 W9: §5 rule 4 pairs a CONCLUDING verdict with its tip's
    open tasks and never lets it print as a lone worklist row -- so the
    filter must exclude anything `concluding` outright, not merely statuses
    outside the standard log type's `[accepted]` list. A project whose
    overlay declares `on_hold` satisfying gets the rule-4 authored pairing
    and NO derived row; a filter testing the status value alone would list
    this tip as an open decision it has actually decided."""
    write_project_config(
        tmp_path,
        CONFIG + "types:\n  log:\n    satisfying_statuses: [accepted, on_hold]\n",
    )
    (tmp_path / "items").mkdir()
    (tmp_path / "items" / "log.yaml").write_text(
        "defaults: { type: log }\n"
        "items:\n"
        "  - {id: LOG-042, summary: Head., date: 2026-08-30}\n"
        "  - id: LOG-043\n"
        "    summary: Held, but satisfying in this project.\n"
        "    date: 2026-09-01\n"
        "    follows: LOG-042\n"
        "    status: on_hold\n"
        "    tasks: [{id: t1, text: Work the decision leaves., state: open}]\n",
        encoding="utf-8",
    )
    config = str(tmp_path / "refdes-project.yaml")
    _warm(tmp_path, config, capsys)
    assert _run(config, "work") == 0
    out = capsys.readouterr().out
    lines = out.splitlines()
    verdict_at = next(i for i, line in enumerate(lines) if line.startswith("Verdict: on_hold"))
    task_at = next(i for i, line in enumerate(lines) if "Work the decision leaves." in line)
    assert verdict_at < task_at  # rule 4's authored pairing...
    assert "verdict" not in _derived_groups(out)  # ...and never a lone derived row


def test_fork_row_self_closes_when_the_branches_merge(tmp_path, capsys):
    """The fork derived row is not a persistent "resolved" flag: merge the two
    tips with a continuation and the fork is gone -- the row closes itself."""
    config = _setup(tmp_path, ("log.yaml", FORK))
    _fork_from_bare(tmp_path, config, capsys)
    assert _run(config, "work") == 0
    assert _derived_groups(capsys.readouterr().out)["fork"] == [
        "LOG-001  tips LOG-002, LOG-003"
    ]

    log = tmp_path / "items" / "log.yaml"
    log.write_text(
        log.read_text(encoding="utf-8")
        + "  - id: LOG-004\n"
        "    summary: Merge of the two branches.\n"
        "    date: 2026-09-05\n"
        "    follows: [LOG-002, LOG-003]\n",
        encoding="utf-8",
    )
    assert _run(config, "work") == 0
    assert "fork" not in _derived_groups(capsys.readouterr().out)


def test_blocked_and_check_rows_self_close(tmp_path, capsys):
    """The cascade and the check self-close on their own remedies: removing the
    `blocked_by:` edge and moving the calc under the bound. Both live in the
    gaps file (the authored file is a separate file and stays untouched)."""
    config = _gaps(tmp_path)
    _warm(tmp_path, config, capsys)
    task_file = tmp_path / "items" / "thread.yaml"
    task_bytes = task_file.read_bytes()
    assert _run(config, "work") == 0
    before = _derived_groups(capsys.readouterr().out)
    assert "LOG-011  by CMP-001 (candidate)" in before["blocked"]
    assert "LOG-010  P_diss violates BND-001" in before["check"]

    gaps = tmp_path / "items" / "gaps.yaml"
    # The warm run froze/expanded `blocked_by: CMP-001` to its composite form,
    # so match the whole line regardless of the target's key suffix.
    gaps.write_text(
        re.sub(r"    blocked_by: CMP-001[^\n]*\n", "", gaps.read_text(encoding="utf-8")).replace(
            "P_diss = 2 W", "P_diss = 0.1 W"
        ),
        encoding="utf-8",
    )
    assert _run(config, "work") == 0
    after = _derived_groups(capsys.readouterr().out)
    assert "blocked" not in after  # the edge is gone: the row closed itself
    assert "check" not in after  # the calc is under the bound: the row closed itself
    assert task_file.read_bytes() == task_bytes  # authored tasks never touched


# ------------------------------------------------------------------- --as-of


def test_as_of_adds_relative_ages_and_without_it_there_are_none(tmp_path, capsys):
    """§5 rule 3, both halves through `work`: the declaring entry and date
    always print; a relative span exists only under an explicit --as-of."""
    config = _authored(tmp_path)
    _warm(tmp_path, config, capsys)
    assert _run(config, "work", "--as-of", "2026-09-02") == 0
    out = capsys.readouterr().out
    assert "(open since LOG-001, 2026-08-30 -- 3 days)" in out
    assert _run(config, "work") == 0
    assert " -- 3 days" not in capsys.readouterr().out


def test_output_does_not_depend_on_the_wall_clock(tmp_path, capsys):
    """The plan's reproducibility rule for the command: two runs with the clock
    two years apart print the same bytes. The relative-span pattern is asserted
    absent too, because patching `time.time` alone would not move a
    `datetime.now()` read -- and this command's age path reads no clock at all
    (`threads.py` imports none, pinned by tests/test_threads_projection.py)."""
    config = _authored(tmp_path)
    _warm(tmp_path, config, capsys)
    assert _run(config, "work") == 0
    first = capsys.readouterr().out
    with mock.patch("time.time", return_value=1_700_000_000.0):
        assert _run(config, "work") == 0
    second = capsys.readouterr().out
    assert second == first
    assert first.startswith("Worklist:")  # sanity: there was real output
    assert not re.search(r" -- \d+ days?\b", first)  # no relative span without --as-of


# ---------------------------------------------------------------------- --json


def test_json_is_valid_on_stdout_even_on_a_first_run_that_mints_keys(tmp_path, capsys):
    """The H7b review's finding, done right in `work`: on a cold tree the load
    mints keys (a real write it must announce), but stdout stays pure JSON --
    the notice goes to stderr. The payload is the whole worklist projection
    {threads, derived}."""
    config = _setup(tmp_path, ("thread.yaml", AUTHORED), ("gaps.yaml", GAPS))
    assert _run(config, "work", "--json") == 0
    captured = capsys.readouterr()
    payload = json.loads(captured.out)  # would raise if a notice leaked onto stdout
    assert set(payload) == {"threads", "derived"}
    assert any(row["kind"] == "coverage" for row in payload["derived"])
    assert "minted" in captured.err  # the load's own write is announced on stderr
    # And --json + --as-of is refused (exit 2): the projection is clock-free.
    assert _run(config, "work", "--json", "--as-of", "2026-09-02") == 2


def _corrupt_store(tmp_path):
    """Break the capture store's first event file, as thread's test file does
    for its B3 pin."""
    events = tmp_path / ".refdes" / "history" / "events"
    (first,) = sorted(events.glob("*.yaml"))
    first.write_text("kind: [\n", encoding="utf-8")


def test_json_names_the_unreadable_store_in_diagnostics(tmp_path, capsys):
    """Review #194 W2 (the work-side mirror of thread's B3 pin, against the
    one helper both commands now build their entry through): the projection
    swallows an unreadable capture store by design, so the machine door
    carries the failure in a `diagnostics` entry shaped exactly like the
    index payload's and `thread --json`'s -- and the worklist half it does
    not degrade (the authored group) still answers."""
    config = _authored(tmp_path)
    _warm(tmp_path, config, capsys)
    _corrupt_store(tmp_path)
    assert _run(config, "work", "--json") == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["threads"], "the worklist half is intact"
    assert all(view["captured"] == [] for view in payload["threads"])  # those rows did vanish --
    (diagnostic,) = payload["diagnostics"]
    assert diagnostic["level"] == "warning"
    assert "could not be read" in diagnostic["message"]  # -- and the payload says so
    assert set(diagnostic) == {"level", "message", "file", "line", "item"}
    assert all("diagnostics" not in view for view in payload["threads"])


def test_bad_as_of_date_is_loud(tmp_path, capsys):
    config = _authored(tmp_path)
    assert _run(config, "work", "--as-of", "not-a-date") == 2
    assert "--as-of" in capsys.readouterr().err


# ------------------------------------------------------------------ exit codes


def test_a_non_empty_worklist_still_exits_zero(tmp_path, capsys):
    """`refdes work` is a read/list command, not a gate (H8 is): every derived
    gap in the project does not change the exit code."""
    config = _gaps(tmp_path)
    _warm(tmp_path, config, capsys)
    assert _run(config, "work") == 0
    out = capsys.readouterr().out
    assert cli_mod.THREAD_DERIVED_HEADING in out
    # Review #194 W4: a real derived row, not just the heading — the heading
    # prints even on an empty block (`(none)`), so it proved nothing.
    assert "    BND-001  uncovered" in out.splitlines()


def test_a_project_with_nothing_open_prints_the_two_empty_groups(tmp_path, capsys):
    """No threads, no gaps: both groups still print (the group's presence is
    part of the two-groups structure), the authored group says so plainly."""
    config = _setup(tmp_path, ("only.yaml", "defaults: { type: log }\nitems:\n  - {id: LOG-001, summary: Solo., date: 2026-08-01}\n"))
    assert _run(config, "work") == 0
    lines = capsys.readouterr().out.splitlines()
    assert "  (no open tasks authored)" in lines
    assert cli_mod.THREAD_DERIVED_HEADING in lines
    assert "  (none)" in lines


def test_a_thread_whose_tasks_are_all_settled_is_not_on_the_worklist(tmp_path, capsys):
    """A real thread (so it is in the projection) whose tip's only task is done
    contributes NO authored block -- a worklist of open work does not print an
    empty per-tip block -- so the authored group stays `(no open tasks
    authored)` even though a thread exists."""
    text = (
        "defaults: { type: log }\n"
        "items:\n"
        "  - {id: LOG-001, summary: Head., date: 2026-08-01, tasks: [{id: t1, text: Done thing., state: done}]}\n"
        "  - {id: LOG-002, summary: Tip., date: 2026-08-02, follows: LOG-001}\n"
    )
    config = _setup(tmp_path, ("thread.yaml", text))
    _warm(tmp_path, config, capsys)
    assert _run(config, "work") == 0
    out = capsys.readouterr().out
    assert "  (no open tasks authored)" in out.splitlines()
    assert "Tasks at" not in out  # no empty per-tip block for a settled tip


def test_unparsable_file_is_reported_with_the_listing_intact(tmp_path, capsys):
    """cmd_ls's posture: the parse error goes to stderr and the exit is 1, but
    the part of the project that did load still prints its worklist."""
    config = _gaps(tmp_path)
    _warm(tmp_path, config, capsys)
    (tmp_path / "items" / "broken.yaml").write_text("items: [\n", encoding="utf-8")
    assert _run(config, "work") == 1
    captured = capsys.readouterr()
    assert "Worklist:" in captured.out
    assert captured.err.strip()


# --------------------------------------------------------------------- writes


def test_no_write_run_writes_nothing(tmp_path, capsys):
    """The plan's tree-hash rule, proven on a tree a writable run WOULD change
    (review #194 W1: the old version warmed the tree first, after which even a
    plain writable `work` left it identical -- vacuous). Phase one proves a
    cold writable `work` really does change the tree (it mints keys into the
    item files); phase two runs `--no-write` on a FRESH cold project and
    proves its tree is untouched -- the store opens read-only and the build
    runs `seal_write=False`, so nothing at all lands."""
    config = _gaps(tmp_path)
    before = _tree(tmp_path)
    assert _run(config, "work") == 0  # writable, on a COLD tree
    capsys.readouterr()
    after = _tree(tmp_path)
    assert after != before, "a cold writable run must change this tree or the test is vacuous"
    assert "key:" in (tmp_path / "items" / "thread.yaml").read_text(encoding="utf-8")

    fresh = tmp_path / "fresh"
    fresh.mkdir()
    fresh_config = _gaps(fresh)  # the same cold project, untouched again
    fresh_before = _tree(fresh)
    assert _run(fresh_config, "--no-write", "work") == 0
    assert _tree(fresh) == fresh_before


def test_the_command_writes_no_seal_even_on_a_type_that_seals_on_build(tmp_path, capsys):
    """The plan's "neither appears in the sealing path" rule, on a fixture that
    ACTUALLY seals (the H7b review found its own seal test vacuous because its
    fixture never did). A `log` type overridden to `sealing: build` writes
    `.refdes/log-seal.yaml` under `refdes build`; `refdes work` -- even a plain
    writable run -- must not. The final assertion proves the fixture really
    seals, so the test cannot pass by construction."""
    write_project_config(tmp_path, CONFIG)
    (tmp_path / "refdes-schema.yaml").write_text(
        "types:\n"
        "  log:\n"
        "    prefix: LOG\n"
        "    append_only: true\n"
        "    sealing: build\n"
        "    fields:\n"
        "      summary: { type: text, required: true }\n",
        encoding="utf-8",
    )
    (tmp_path / "items").mkdir()
    (tmp_path / "items" / "log.yaml").write_text(
        "defaults: { type: log }\n"
        "items:\n"
        "  - id: LOG-001\n    summary: First.\n"
        "  - id: LOG-002\n    summary: Second.\n    follows: LOG-001\n",
        encoding="utf-8",
    )
    config = str(tmp_path / "refdes-project.yaml")

    # A writable load first (keys/expansions are the load's own, not a seal),
    # then clear any stray seal so the work run is measured against a clean tree.
    loader.load_tree(config)
    seal = tmp_path / ".refdes" / "log-seal.yaml"
    if seal.exists():
        seal.unlink()

    assert _run(config, "work") == 0
    capsys.readouterr()
    assert not seal.exists()

    # Non-vacuity: the same project, built normally, does write the seal.
    assert _run(config, "build") == 0
    assert seal.exists()
