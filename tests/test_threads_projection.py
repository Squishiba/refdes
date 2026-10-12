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
from refdes import chains, history, keys, parse, render, threads
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
    with mock.patch.object(
        render.threads_mod, "threads_projection", lambda project, *, graph=None, captures=None: []
    ):
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


def test_items_json_reads_the_capture_store_once(tmp_path, monkeypatch):
    """Review B4: `refdes index` used to parse the whole event store twice
    in one call -- once inside the thread projection's capture rows, once
    for the per-item `captured` keys. `items_json` now reads the index
    once and hands it to the projection; this pins the read count around
    the call itself (any diagnostic read inside `build` belongs to that
    build, not to this export)."""
    project = _derived_project(tmp_path)
    calls: list = []
    real = history.capture_index

    def counting(p):
        calls.append(p)
        return real(p)

    monkeypatch.setattr(history, "capture_index", counting)
    payload = render.items_json(project)
    assert "threads" in payload  # the shared read really did feed both halves
    assert len(calls) == 1


def test_projection_never_reads_a_clock(tmp_path):
    """§5 rule 3's reproducibility rule: with the wall clock moved about
    three years (epoch 1_700_000_000 is 2023-11-14; the fixture dates are
    2026) the projection's bytes do not move. (Relative spans are H7b's
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

# ------------------------------------------------- the review-fix matrix (H7b)


def test_ambiguous_verdict_is_its_own_state_never_the_undeclared_null(tmp_path):
    """H7b review fix (a): two merge parents at the same distance declaring
    *different* statuses make the fold ambiguous, and `(None, None)` is byte
    for byte what "nothing ever declared a status" returns -- so without a
    distinct state the projection shows the ambiguity as a blank, exactly
    the collapse §5 rule 3 forbids for task lists. LOG-005's branch (silent
    ancestry) keeps `verdict: null`; LOG-009's refuses and must say so."""
    text = (
        "defaults: { type: log }\n"
        "items:\n"
        "  - {id: LOG-007, summary: Settled left., date: 2026-08-07, status: accepted}\n"
        "  - {id: LOG-008, summary: Held right., date: 2026-08-08, status: proposed}\n"
        "  - {id: LOG-009, summary: Silent merge., date: 2026-08-09, follows: [LOG-007, LOG-008]}\n"
        "  - {id: LOG-005, summary: Silent head., date: 2026-08-05}\n"
        "  - {id: LOG-006, summary: Silent continuation., date: 2026-08-06, follows: LOG-005}\n"
    )
    project = _project(tmp_path, text)
    views = threads.threads_projection(project)

    merged = _thread(views, "LOG-007")["branches"][0]["verdict"]
    assert merged["state"] == "conflicting"
    assert merged["status"] is None
    assert merged["concluding"] is False
    # The distinctness the fix exists for: ambiguous != never declared.
    silent = _thread(views, "LOG-005")["branches"][0]["verdict"]
    assert silent is None


def test_declared_verdicts_carry_their_state_too(tmp_path):
    """Uniform discriminator: a folded verdict is `state: resolved` with
    its status, so a consumer never has to guess whether `status: null`
    means conflicting or absent (it can't -- the absent case is a null
    verdict)."""
    project = _project(tmp_path, ONE_TIP)
    (view,) = threads.threads_projection(project)
    verdict = view["branches"][0]["verdict"]
    assert verdict["state"] == "resolved"
    assert verdict["status"] == "accepted"


def test_all_malformed_task_list_is_declared_not_cleared(tmp_path):
    """H7b review fix (b): a declared, non-empty `tasks:` whose rows are all
    malformed has zero *valid* rows -- but it is not the author's explicit
    `tasks: []`. Reporting it `cleared` would hide the validation error
    behind the one state that means "the author closed everything". The
    state is the raw declaration's posture; `malformed` counts the drops
    `build.validate_items` already reported."""
    text = (
        "defaults: { type: log }\n"
        "items:\n"
        "  - id: LOG-001\n"
        "    summary: Nonsense list.\n"
        "    date: 2026-08-01\n"
        "    tasks: [measure the rail]\n"
        "  - id: LOG-002\n"
        "    summary: Silent continuation.\n"
        "    date: 2026-08-02\n"
        "    follows: LOG-001\n"
    )
    project = _project(tmp_path, text)
    assert project.errors  # build.validate_items reported the row
    (view,) = threads.threads_projection(project)
    tasks = view["branches"][0]["tasks"]
    assert tasks["state"] == "declared"
    assert tasks["rows"] == []
    assert tasks["malformed"] == 1
    # A clean declaration carries the key only when something was dropped.
    clean = _project(tmp_path, ONE_TIP)
    (view,) = threads.threads_projection(clean)
    assert "malformed" not in view["branches"][0]["tasks"]


def test_partially_malformed_list_keeps_the_valid_rows_and_counts_the_rest(tmp_path):
    """The count posture has to hold beside non-empty valid rows, not only
    in the all-dropped case: one malformed row next to one good row is
    still `declared`, the good row still prints (with its `open_since`),
    and `malformed` counts exactly what was dropped."""
    text = (
        "defaults: { type: log }\n"
        "items:\n"
        "  - id: LOG-001\n"
        "    summary: Mixed list.\n"
        "    date: 2026-08-01\n"
        "    tasks:\n"
        "      - {id: t1, text: Measure the rail., state: open}\n"
        "      - not even a mapping\n"
        "  - id: LOG-002\n"
        "    summary: Silent continuation.\n"
        "    date: 2026-08-02\n"
        "    follows: LOG-001\n"
    )
    project = _project(tmp_path, text)
    assert project.errors  # the malformed row was reported as everywhere else
    (view,) = threads.threads_projection(project)
    tasks = view["branches"][0]["tasks"]
    assert tasks["state"] == "declared"
    assert tasks["malformed"] == 1
    assert [(row["id"], row["state"]) for row in tasks["rows"]] == [("t1", "open")]
    assert tasks["rows"][0]["open_since"] == {"entry": "LOG-001", "date": "2026-08-01"}


def test_task_rows_are_copied_never_the_authored_field_itself(tmp_path):
    """H7b review fix (d)'s factual half: `rows` are copies -- `open_since`
    is *added* to the copy -- so a consumer poking a projection row can
    never rewrite `item.fields` (or the file through the item)."""
    project = _project(tmp_path, ONE_TIP)
    (view,) = threads.threads_projection(project)
    tasks = view["branches"][0]["tasks"]
    row = tasks["rows"][0]
    authored = project.item_by_id("LOG-001").fields["tasks"][0]
    assert row == {**authored, "open_since": {"entry": "LOG-001", "date": "2026-08-30"}}
    row["text"] = "clobbered"
    assert authored["text"] != "clobbered"
    assert "open_since" not in authored


def test_thread_list_is_ordered_by_ref_the_only_order_the_docs_allow(tmp_path):
    """H7b review fix (c): §5/§6 order entries *within* a thread (oldest
    first) and say nothing about the order of the *list of threads*; the
    docstring used to claim "oldest-root first", which the code never did
    -- it sorts by root ref. Pinned here with roots whose dates order the
    other way, so a date sort of the list fails this test."""
    text = (
        "defaults: { type: log }\n"
        "items:\n"
        "  - {id: LOG-010, summary: Older thread root., date: 2026-01-01}\n"
        "  - {id: LOG-011, summary: Older continuation., date: 2026-01-02, follows: LOG-010}\n"
        "  - {id: LOG-002, summary: Newer thread root., date: 2026-06-01}\n"
        "  - {id: LOG-003, summary: Newer continuation., date: 2026-06-02, follows: LOG-002}\n"
    )
    project = _project(tmp_path, text)
    refs = [view["ref"] for view in threads.threads_projection(project)]
    assert refs == ["LOG-002", "LOG-010"]


def test_derived_scope_follows_composite_key_targets(tmp_path):
    """H7b review fix (e): `_scope`'s one hop reads `Item.resolved_links`,
    not raw `Item.links` (AGENTS.md: anything walking the graph that reads
    raw links "stops matching the moment a target is composite-expanded").
    With the fixture's `addresses:` hand-rewritten to `REQ-001@<key>`, raw
    links hold a token `item_by_ref` cannot resolve -- only `resolved_links`
    holds the bare label -- so this test is exactly the sabotage."""
    project = _project(tmp_path, DERIVED)
    key = project.item_by_id("REQ-001").key
    assert key
    path = tmp_path / "items" / "log.yaml"
    text = path.read_text(encoding="utf-8")
    composite = text.replace("addresses: REQ-001", f"addresses: REQ-001@{key}")
    assert composite != text
    path.write_text(composite, encoding="utf-8")

    project = _load(tmp_path)
    logger = project.item_by_id("LOG-001")
    assert logger.links["addresses"] == [f"REQ-001@{key}"]  # the raw half
    assert project.item_by_ref(f"REQ-001@{key}") is None  # raw text resolves nowhere
    assert logger.resolved_links["addresses"] == ["REQ-001"]  # the half _scope reads

    (view,) = threads.threads_projection(project)
    assert ("coverage", "REQ-001") in [(row["kind"], row["ref"]) for row in view["derived"]]


# ---------------------------------------------------------------- capture line


def test_thread_without_store_history_has_no_capture_rows(tmp_path):
    """`captured: []` is "the store holds no capture of any member" -- a
    project that never ran a writable command simply has no store, and the
    thread view says so with an empty list rather than failing over it."""
    project = _project(tmp_path, ONE_TIP)
    (view,) = threads.threads_projection(project)
    assert view["captured"] == []


def test_thread_names_the_entries_the_store_holds_captures_for(tmp_path):
    """§6's capture line, as data: a writable load anchors the `follows:`
    edge and captures the predecessor's snapshot, so the thread reports that
    member as captured -- with the event's kind, and `occurred_at: null`
    exactly because a `followed` edge deliberately carries no clock (H2: a
    stamp would give one fact different bytes in two checkouts; §2 says
    nobody may order or gate on it)."""
    from refdes import loader

    write_project_config(tmp_path, CONFIG)
    items = tmp_path / "items"
    items.mkdir(exist_ok=True)
    (items / "log.yaml").write_text(ONE_TIP, encoding="utf-8")
    config = str(tmp_path / "refdes-project.yaml")
    loader.load_tree(config)  # writable: keys, expansion, and the capture
    project, _ = loader.load_tree(config, write=False)
    build_mod.build(project, seal_write=False, reseal=False)

    (view,) = threads.threads_projection(project)
    assert view["captured"] == [
        {"entry": "LOG-001", "kind": "followed", "occurred_at": None}
    ]


# ------------------------------------------------------- the project-wide worklist (H7c)


def test_project_derived_builds_no_chain_graph_when_threads_are_passed(tmp_path):
    """Review #194 W10: the chain graph exists only for the projection, so a
    caller that hands `project_derived` its `threads` must not pay for a
    second parse -- the graph is built lazily now, only when the projection
    still has to run. The spy makes the waste impossible to hide."""
    project = _derived_project(tmp_path)
    views = threads.threads_projection(project)
    with mock.patch.object(
        threads.chains_mod,
        "build_graph",
        side_effect=AssertionError("chain graph built despite a passed-in projection"),
    ):
        rows = threads.project_derived(project, threads=views)
    assert rows and all(row["kind"] in threads._KIND_ORDER for row in rows)


def test_project_derived_lists_each_item_gap_once_project_wide(tmp_path):
    """H7c's whole-project derived block. The item-level rows are the SAME rows
    the per-thread derived block reads (`_rows_for_subject`), but computed over
    every local item once: REQ-002 is open coverage that no thread touches, so
    no per-thread block would ever show it, while the worklist must (it is a
    real gap). Each row is present exactly once (no thread scoping to double a
    gap two threads could touch), and the ordering follows §5's table
    (coverage < blocked < citation) so the derived block is deterministic."""
    project = _derived_project(tmp_path)
    rows = threads.project_derived(project)
    seen = [(row["kind"], row["ref"]) for row in rows]
    # REQ-002 is nobody's thread row but the project's own coverage gap.
    assert ("coverage", "REQ-002") in seen
    # The per-thread gap still appears, once.
    assert ("coverage", "REQ-001") in seen
    assert ("blocked", "LOG-001") in seen
    assert ("citation", "LOG-001") in seen
    # Exactly once each, no duplicates from scoping.
    assert len(seen) == len(set(seen))
    # Ordering follows the shared kind order against an INDEPENDENT literal
    # (review #194 W12's line was this one; #194 C3 keeps it honest): a
    # scramble of threads._KIND_ORDER must fail here, not agree with it.
    KIND_ORDER = {"coverage": 0, "verdict": 1, "blocked": 2, "check": 3, "citation": 4, "fork": 5}
    assert sorted(seen, key=lambda row: KIND_ORDER[row[0]]) == seen


def test_project_derived_adds_verdict_and_fork_rows_from_the_projection(tmp_path):
    """The two row kinds unique to the whole-project listing, read from the
    projection (no fold recomputed): a `verdict` row for a branch whose folded
    status is still an open decision (`proposed`), and a `fork` row naming each
    forked thread's own tips. The head's `accepted` list is settled, so it is
    not a worklist row (rule 4 pairs it with its open tasks instead)."""
    project = _project(tmp_path, FORK)
    views = threads.threads_projection(project)
    rows = threads.project_derived(project, threads=views)
    verdict = [row for row in rows if row["kind"] == "verdict"]
    assert [(row["ref"], row["status"]) for row in verdict] == [("LOG-002", "proposed")]
    fork = [row for row in rows if row["kind"] == "fork"]
    assert [(row["ref"], row["tips"]) for row in fork] == [("LOG-001", ["LOG-002", "LOG-003"])]


def test_project_derived_writes_nothing_and_reads_no_clock(tmp_path):
    """The same two reproducibility guarantees the projection carries: the
    worklist is a pure read and its bytes never move with the wall clock."""
    project = _derived_project(tmp_path)
    before = _snapshot(tmp_path)
    first = json.dumps(threads.project_derived(project), sort_keys=True, default=str)
    with mock.patch("time.time", return_value=1_700_000_000.0):
        second = json.dumps(threads.project_derived(project), sort_keys=True, default=str)
    assert first == second
    assert _snapshot(tmp_path) == before
