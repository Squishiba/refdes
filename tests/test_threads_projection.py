"""Living notes phase H7a: the thread-view projection and the index key.

Every bullet under plan §H7 "Verified against" that belongs to the projection
half is a test here (the two CLI commands are H7b/H7c): one tip's tasks with
age, a forked thread with one task block and one branch-local verdict per tip
and no single current status anywhere, derived rows that self-close without
recording anything, the `threads` key present for threaded projects and
absent otherwise, and the two reproducibility guarantees of the read surface
(no clock, no writes). The sabotage matrix is recorded in
`in-prog-logs/living-notes-h7a-threads-projection.txt`.

The shape rules under test are living-notes.md §5's five binding rules read as
*structure* (two separate groups, self-closing derived rows, absolute ages,
verdict next to its tasks, fork never collapsed) and §6's "one query service"
(`refdes.threads.threads_projection` is the single fold/tip/derived-row
answer every surface reads).
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from unittest import mock

from conftest import write_project_config

from refdes import build as build_mod
from refdes import chains, keys, parse, render, threads
from refdes.schema import load_project

CONFIG = (
    "site: { title: Threads, out: _site }\n"
    "standard: { base: hardware, version: 3 }\n"
)

OPEN_TASK = "      - {id: T-thermal-model, text: Model worst-case copper temperature., state: open}\n"
OPEN_TASK_DONE = OPEN_TASK.replace("state: open", "state: done")


def _load(root):
    project = load_project(config_path=str(root / "refdes-project.yaml"))
    parse.load_items(project)
    keys.mint_missing(project)
    build_mod.build(project)
    return project


def _project(tmp_path, items_yaml):
    write_project_config(tmp_path, CONFIG)
    items = tmp_path / "items"
    items.mkdir(exist_ok=True)
    (items / "log.yaml").write_text(items_yaml, encoding="utf-8")
    return _load(tmp_path)


def _thread(views, ref):
    (view,) = [v for v in views if v["ref"] == ref]
    return view


def _json(view) -> str:
    # default=str: item.fields carries date objects, which render_site's own
    # dump likewise stringifies -- irrelevant to the projection (its own
    # dates are str already) but the payload tests compare whole payloads.
    return json.dumps(view, sort_keys=True, default=str)


# ---------------------------------------------------------------- one tip


ONE_TIP = (
    "defaults: { type: log }\n"
    "items:\n"
    "  - id: LOG-001\n"
    "    summary: Power work list.\n"
    "    date: 2026-08-30\n"
    "    tasks:\n"
    f"{OPEN_TASK}"
    "  - id: LOG-002\n"
    "    summary: Thermal modelling accepted.\n"
    "    date: 2026-09-02\n"
    "    follows: LOG-001\n"
    "    status: accepted\n"
)


def test_one_tip_thread_carries_tasks_with_age_and_verdict_together(tmp_path):
    """Plan §H7: "one-tip thread: header, tip, tasks with age" -- §5 rule 3's
    age is the *declaring* entry and its authored date, not the tip's, and
    §5 rule 4 puts the verdict in the same object as the tasks."""
    project = _project(tmp_path, ONE_TIP)
    (view,) = threads.threads_projection(project)
    assert view["ref"] == "LOG-001"
    assert view["entries"] == ["LOG-001", "LOG-002"]
    assert view["tips"] == ["LOG-002"]
    assert view["forked"] is False

    (branch,) = view["branches"]
    assert branch["tip"] == "LOG-002"
    tasks = branch["tasks"]
    assert tasks["state"] == "declared"
    assert tasks["declared_by"] == "LOG-001"
    assert tasks["declared_on"] == "2026-08-30"
    (open_row,) = [row for row in tasks["rows"] if row["state"] == "open"]
    # Absolute authored date only: the projection has no clock to compute a
    # relative span with, and a byte-for-byte second run proves it below.
    assert open_row["open_since"] == {"entry": "LOG-001", "date": "2026-08-30"}

    verdict = branch["verdict"]
    assert verdict is not None
    assert verdict["status"] == "accepted"
    assert verdict["declared_by"] == "LOG-002"
    assert verdict["declared_on"] == "2026-09-02"
    # `accepted` is the merged log type's satisfying_statuses -- the
    # concluding question is blocked._is_settled's, pointed at the tip.
    assert verdict["concluding"] is True


def test_verdict_fold_is_resolve_current_on_a_one_tip_thread(tmp_path):
    """`chains.fold_at_tip` is `resolve_current_with_source`'s own fold
    anchored at the tip, so on a one-tip thread the two agree on both the
    value and the declaring entry -- the equivalence decision 2 rests on."""
    project = _project(tmp_path, ONE_TIP)
    start = project.item_by_id("LOG-001")
    tip = project.item_by_id("LOG-002")
    folded = chains.fold_at_tip(project, tip, "status", graph=None)
    current = chains.resolve_current_with_source(project, start, "status")
    assert folded[0] == current[0]
    assert folded[1] is current[1]


def test_non_threaded_project_has_no_threads_key(tmp_path):
    """A lone entry with no `follows:` either way is not a thread, so the
    index payload carries no `threads` key at all -- the absent-key rule
    that keeps a non-threaded project byte-identical (pinned end-to-end by
    tests/fixtures/no_theme_build_hashes.json via tests/test_theme.py)."""
    project = _project(
        tmp_path,
        "defaults: { type: log }\n"
        "items:\n"
        "  - {id: LOG-001, summary: Solo head., date: 2026-08-01}\n"
        "  - {id: LOG-002, summary: Other head., date: 2026-08-02}\n",
    )
    payload = render.items_json(project)
    assert "threads" not in payload


def test_threads_key_is_the_only_payload_difference(tmp_path):
    """Adding the key must not perturb a single other byte of `items_json`:
    the payload minus `threads` equals the payload with the projection
    forced empty."""
    project = _project(tmp_path, ONE_TIP)
    with_threads = render.items_json(project)
    assert "threads" in with_threads
    without = dict(with_threads)
    del without["threads"]
    # Same loaded project both times (items_json is a pure read; two fresh
    # loads of one tree are not byte-comparable anyway -- the first build
    # mints keys and expands links into the files). Unsorted dumps: the
    # claim is byte-identity including key order, not just equal content.
    dump = lambda payload: json.dumps(payload, default=str)
    with mock.patch.object(render.threads_mod, "threads_projection", lambda project, *, graph=None: []):
        forced = render.items_json(project)
    assert dump(forced) == dump(without)


# ---------------------------------------------------------------- the fork


FORK = (
    "defaults: { type: log }\n"
    "items:\n"
    "  - id: LOG-001\n"
    "    summary: Power work list.\n"
    "    date: 2026-08-30\n"
    "    tasks:\n"
    f"{OPEN_TASK}"
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


def test_fork_keeps_everything_per_tip_and_collapses_nothing(tmp_path):
    """Plan §H7: "both tips listed, one Tasks block per branch, and no line
    anywhere asserting a single current status" -- here "no line" is "no
    key": the thread object itself carries no status/verdict/tasks at all,
    so a client cannot read one even by accident."""
    project = _project(tmp_path, FORK)
    (view,) = threads.threads_projection(project)
    assert view["forked"] is True
    assert view["tips"] == ["LOG-002", "LOG-003"]
    assert not {"status", "verdict", "tasks"} & set(view)

    branches = {branch["tip"]: branch for branch in view["branches"]}
    assert sorted(branches) == ["LOG-002", "LOG-003"]
    # Branch-local task lists: LOG-002 folds the head's list, LOG-003 its
    # own -- never a union, never one global list.
    assert [row["id"] for row in branches["LOG-002"]["tasks"]["rows"]] == ["T-thermal-model"]
    assert [row["id"] for row in branches["LOG-003"]["tasks"]["rows"]] == ["T-decoupling"]


def test_forked_verdicts_are_branch_local_where_resolve_current_is_none(tmp_path):
    """§5 "forked values remain branch-local": resolve_current (the thread's
    single conclusion) is None on a fork, while each branch still carries
    its own folded verdict -- LOG-002 its declared `proposed`, LOG-003
    nothing (its ancestry never declared a status)."""
    project = _project(tmp_path, FORK)
    assert chains.resolve_current(project, project.item_by_id("LOG-001"), "status") is None
    (view,) = threads.threads_projection(project)
    branches = {branch["tip"]: branch for branch in view["branches"]}
    assert branches["LOG-002"]["verdict"]["status"] == "proposed"
    assert branches["LOG-002"]["verdict"]["concluding"] is False
    assert branches["LOG-003"]["verdict"] is None


# ---------------------------------------------------- the fold's list states


def test_the_fold_list_states_stay_distinct(tmp_path):
    """`fold_tasks`' four postures stay four distinct `tasks.state` values --
    declared, cleared (an explicit `tasks: []`), undeclared (never
    declared), and ambiguous ("task reconciliation required": rows null,
    not rows []) -- because §5 rule 1 forbids collapsing a no-list into an
    empty list."""
    text = (
        "defaults: { type: log }\n"
        "items:\n"
        "  - {id: LOG-001, summary: Declared head., date: 2026-08-01, tasks: [{id: t1, text: One., state: open}]}\n"
        "  - {id: LOG-002, summary: Silent continuation., date: 2026-08-02, follows: LOG-001}\n"
        "  - {id: LOG-003, summary: List on the head., date: 2026-08-03, tasks: [{id: t2, text: Two., state: open}]}\n"
        "  - {id: LOG-004, summary: Cleared at the tip., date: 2026-08-04, follows: LOG-003, tasks: []}\n"
        "  - {id: LOG-005, summary: Undeclared head., date: 2026-08-05}\n"
        "  - {id: LOG-006, summary: Silent continuation., date: 2026-08-06, follows: LOG-005}\n"
        "  - {id: LOG-007, summary: Merge parent left., date: 2026-08-07, tasks: [{id: a, text: Left., state: open}]}\n"
        "  - {id: LOG-008, summary: Merge parent right., date: 2026-08-08, tasks: [{id: b, text: Right., state: open}]}\n"
        "  - {id: LOG-009, summary: Silent merge., date: 2026-08-09, follows: [LOG-007, LOG-008]}\n"
    )
    project = _project(tmp_path, text)
    views = threads.threads_projection(project)

    declared = _thread(views, "LOG-001")["branches"][0]["tasks"]
    assert declared["state"] == "declared"
    assert declared["declared_by"] == "LOG-001"
    cleared = _thread(views, "LOG-003")["branches"][0]["tasks"]
    assert cleared["state"] == "cleared"
    assert cleared["rows"] == []
    assert cleared["declared_by"] == "LOG-004"
    undeclared = _thread(views, "LOG-005")["branches"][0]["tasks"]
    assert undeclared["state"] == "undeclared"
    assert undeclared["rows"] is None
    ambiguous = _thread(views, "LOG-007")["branches"][0]["tasks"]
    assert ambiguous["state"] == "ambiguous"
    assert ambiguous["rows"] is None


# -------------------------------------------------------------- derived rows


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
    "    blocked_by: CMP-001\n"
    "    citations: [{path: notes/datasheet.pdf}]\n"
    "  - id: REQ-001\n"
    "    type: requirement\n"
    "    title: Idle current budget\n"
    "    status: active\n"
    "    body: The idle rail must stay under 10 uA.\n"
    "  - id: REQ-002\n"
    "    type: requirement\n"
    "    title: Untouched requirement\n"
    "    status: active\n"
    "    body: Nobody has worked on this one yet.\n"
    "  - id: CMP-001\n"
    "    type: component\n"
    "    title: LDO regulator\n"
    "    status: candidate\n"
)


def _derived_project(tmp_path):
    (tmp_path / "notes").mkdir(exist_ok=True)
    (tmp_path / "notes" / "datasheet.pdf").write_bytes(b"%PDF-1.4 fake\n")
    return _project(tmp_path, DERIVED)


def test_derived_rows_read_like_problems_not_tasks(tmp_path):
    """§5 rule 1's structural separation, mechanically: derived rows carry no
    task `id`, apply to thread members AND to what the members' links point
    at one hop out (the §6 example's `coverage REQ-...` / `citation
    CMP-...`), respect the lifecycle rules' own selection (REQ-002 is open
    but nobody touches it, so it is no thread's row), and sort coverage <
    blocked < citation."""
    project = _derived_project(tmp_path)
    (view,) = threads.threads_projection(project)
    rows = view["derived"]
    assert [(row["kind"], row["ref"]) for row in rows] == [
        ("coverage", "REQ-001"),
        ("blocked", "LOG-001"),
        ("citation", "LOG-001"),
    ]
    assert all("id" not in row for row in rows)
    coverage = rows[0]
    # addressed by the log's own `addresses:` link: not verified, and
    # `uncovered` is reserved for stage open -- the lifecycle rules' line.
    assert coverage["problem"] == "unverified"
    assert coverage["stage"] == "addressed"
    blocked = rows[1]
    assert blocked["path"] == ["LOG-001", "CMP-001"]
    assert blocked["root"] == "CMP-001"
    assert blocked["root_status"] == "candidate"
    assert blocked["stale"] is False
    citation = rows[2]
    assert citation["problem"] == "unpinned"
    assert citation["path"] == "notes/datasheet.pdf"


def test_derived_rows_self_close_without_recording_anything(tmp_path):
    """§5 rule 2: fix the gap, re-read, the row is gone -- and no "done" was
    recorded anywhere: the thread's authored task list is identical across
    the fix, still carrying the same open task. The fix here is a real
    engineering fix (a passing test verifying the requirement), not a tick.

    The blocked and citation rows deliberately stay out of this test: their
    remedies (remove the edge / pin the document) are theirs to make, and a
    stale or unpinned row that a different edit would clear proves nothing
    about self-closing."""
    project = _project(
        tmp_path,
        "items:\n"
        "  - id: LOG-000\n"
        "    type: log\n"
        "    summary: Idle current thread opens.\n"
        "    date: 2026-08-30\n"
        "  - id: LOG-001\n"
        "    type: log\n"
        "    summary: Idle current investigation.\n"
        "    date: 2026-09-01\n"
        "    follows: LOG-000\n"
        "    tasks: [{id: t1, text: Measure idle current., state: open}]\n"
        "    addresses: REQ-001\n"
        "  - id: REQ-001\n"
        "    type: requirement\n"
        "    title: Idle current budget\n"
        "    status: active\n"
        "    body: The idle rail must stay under 10 uA.\n",
    )
    (view,) = threads.threads_projection(project)
    before_tasks = view["branches"][0]["tasks"]
    assert [(row["kind"], row["ref"]) for row in view["derived"]] == [("coverage", "REQ-001")]

    (tmp_path / "items" / "test.yaml").write_text(
        "items:\n"
        "  - id: TST-001\n"
        "    type: test\n"
        "    title: Idle current measured\n"
        "    status: passing\n"
        "    verifies: REQ-001\n",
        encoding="utf-8",
    )
    fixed = _load(tmp_path)
    (view,) = threads.threads_projection(fixed)
    assert view["derived"] == []
    assert view["branches"][0]["tasks"] == before_tasks


# ------------------------------------------------------------------ checks


def test_failing_check_becomes_a_derived_row(tmp_path):
    """§5's table names failed checks as worklist material -- read from
    `item.checks` (build.run_checks' result), with the check's own detail."""
    text = (
        "items:\n"
        "  - id: BND-001\n"
        "    type: bound\n"
        "    title: Idle power\n"
        "    status: active\n"
        "    limit: <= 0.5 W\n"
        "    body: The board may not burn more than half a watt idle.\n"
        "  - id: LOG-001\n"
        "    type: log\n"
        "    summary: Power budget attempt.\n"
        "    date: 2026-09-01\n"
        "    follows: LOG-000\n"
        "    checks: [{value: P_diss, against: BND-001}]\n"
        "    body: |\n"
        "      ```calc\n"
        "      P_diss = 2 W\n"
        "      ```\n"
        "  - id: LOG-000\n"
        "    type: log\n"
        "    summary: Earlier entry.\n"
        "    date: 2026-08-30\n"
    )
    project = _project(tmp_path, text)
    (view,) = threads.threads_projection(project)
    rows = [row for row in view["derived"] if row["kind"] == "check"]
    assert len(rows) == 1
    row = rows[0]
    assert row["ref"] == "LOG-001"
    assert row["value"] == "P_diss"
    assert row["against"] == "BND-001"
    assert row["actual"] and row["limit"]
    assert row["detail"]
    # The bound is one hop out (checks are not links), so it gets no
    # coverage row -- only what the thread actually points at does.
    assert all(row["ref"] != "BND-001" or row["kind"] != "coverage" for row in view["derived"])


# --------------------------------------------------------- reproducibility


def _snapshot(root) -> dict[str, str]:
    out = {}
    for path in sorted(root.rglob("*")):
        if path.is_file():
            out[str(path.relative_to(root))] = hashlib.sha256(path.read_bytes()).hexdigest()
    return out


def test_projection_writes_nothing(tmp_path):
    """The plan's "neither appears in the sealing path" rule, in
    projection form: a build, then projection + items_json, must leave the
    tree byte-identical."""
    project = _derived_project(tmp_path)
    before = _snapshot(tmp_path)
    threads.threads_projection(project)
    render.items_json(project)
    assert _snapshot(tmp_path) == before


def test_projection_never_reads_a_clock(tmp_path):
    """§5 rule 3's reproducibility rule: with the wall clock moved two years
    the projection's bytes do not move. (Relative spans are H7b's
    `--as-of` alone, on top of these absolute fields.)"""
    project = _derived_project(tmp_path)
    first = _json(threads.threads_projection(project))
    with mock.patch("time.time", return_value=1_700_000_000.0):
        second = _json(threads.threads_projection(project))
    assert first == second


def test_module_imports_no_clock():
    """The structural half of the same rule: the module simply has no clock
    to read -- no datetime, no time, no now()/today() calls anywhere in its
    source."""
    source = Path(threads.__file__).read_text(encoding="utf-8")
    assert not re.search(
        r"\bdatetime\b|\btime\b\.|utcnow|utcfromtimestamp|\.today\(|\.now\(",
        source,
    )
