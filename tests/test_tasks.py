"""Living notes phase H6: `tasks:` on the merged log type, and its fold.

Every bullet under plan §H6 "Verified against" is a test here, and every test
that pins a behaviour was sabotage-checked (the record is
`in-prog-logs/living-notes-h6-tasks.txt`): the field's `on_change: log` is
flipped and the fold's machinery is broken one rule at a time, each time with
exactly the tests named here failing and nothing else.

The fold is `chains.fold_tasks`: the existing `_fold_from_tip` walk, reused
per thread tip -- nearest own declaration wins, inherited `defaults:` do not
declare, omission preserves, `tasks: []` clears, a declared list replaces the
whole prior list, differing equally-near declarations are ambiguous, and an
unmerged fork yields one labelled list per tip and no single list anywhere.
Validation (unique task ids, known states) is `build.validate_items`. Naming
rule P6: the noun is always `task`; `work` is reserved for the future
`refdes work` command.
"""

from __future__ import annotations

from conftest import write_project_config

from refdes import build as build_mod
from refdes import chains, history, keys, lifecycle, parse
from refdes.schema import load_project

CONFIG = (
    "site: { title: Tasks, out: _site }\n"
    "standard: { base: hardware, version: 3 }\n"
)

THERMAL = "      - {id: T-thermal-model, text: Model worst-case copper temperature., state: open}\n"
THERMAL_DONE = THERMAL.replace("state: open", "state: done")
DECOUPLING = "      - {id: T-decoupling, text: Recheck decoupling near U14., state: open}\n"


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


def _edit(tmp_path, old: str, new: str) -> None:
    """Edit the items file in place -- never rewrite it wholesale, or keys
    already minted into the entries would be lost."""
    path = tmp_path / "items" / "log.yaml"
    text = path.read_text(encoding="utf-8")
    assert old in text, (old, text)
    path.write_text(text.replace(old, new), encoding="utf-8")


def _head_with_tasks():
    return (
        "defaults: { type: log }\n"
        "items:\n"
        "  - id: LOG-001\n"
        "    summary: Power work list.\n"
        "    date: 2026-08-30\n"
        "    tasks:\n"
        f"{THERMAL}"
    )


def _errors_containing(project, *needles):
    return [d for d in project.errors if all(n in d.message for n in needles)]


# ------------------------------------------------- fold: the settled cases


def test_a_head_with_no_follows_folds_to_itself(tmp_path):
    """"The first task list" is an ordinary log head (§5's decided shape): a
    thread of one, folding its own declaration."""
    project = _project(tmp_path, _head_with_tasks())
    assert not project.errors
    folds = chains.fold_tasks(project, project.item_by_id("LOG-001"))
    assert len(folds) == 1
    fold = folds[0]
    assert fold.tip.id == "LOG-001"
    assert not fold.ambiguous
    assert fold.source is not None and fold.source.id == "LOG-001"
    assert fold.rows == [
        {
            "id": "T-thermal-model",
            "text": "Model worst-case copper temperature.",
            "state": "open",
        }
    ]


def test_omission_preserves_the_nearest_declaration(tmp_path):
    project = _project(
        tmp_path,
        "defaults: { type: log }\n"
        "items:\n"
        "  - id: LOG-001\n"
        "    summary: Power work list.\n"
        "    date: 2026-08-30\n"
        "    tasks:\n"
        f"{THERMAL}"
        "  - id: LOG-002\n"
        "    summary: Still open.\n"
        "    date: 2026-09-01\n"
        "    follows: [LOG-001]\n"
        "  - id: LOG-003\n"
        "    summary: Still open after two silent entries.\n"
        "    date: 2026-09-02\n"
        "    follows: [LOG-002]\n",
    )
    assert not project.errors
    (fold,) = chains.fold_tasks(project, project.item_by_id("LOG-003"))
    assert [row["id"] for row in fold.rows] == ["T-thermal-model"]
    assert fold.source.id == "LOG-001"
    # Asked from the head, the same thread gives the same answer.
    (same,) = chains.fold_tasks(project, project.item_by_id("LOG-001"))
    assert same.rows == fold.rows and same.tip.id == "LOG-003"


def test_a_declared_list_replaces_the_whole_prior_list(tmp_path):
    project = _project(
        tmp_path,
        "defaults: { type: log }\n"
        "items:\n"
        "  - id: LOG-001\n"
        "    summary: First list.\n"
        "    date: 2026-08-30\n"
        "    tasks:\n"
        f"{THERMAL}{DECOUPLING}"
        "  - id: LOG-002\n"
        "    summary: Second list.\n"
        "    date: 2026-09-01\n"
        "    follows: [LOG-001]\n"
        "    tasks:\n"
        f"{DECOUPLING}"
        "  - id: LOG-003\n"
        "    summary: Silence preserves the second list.\n"
        "    date: 2026-09-02\n"
        "    follows: [LOG-002]\n",
    )
    assert not project.errors
    (fold,) = chains.fold_tasks(project, project.item_by_id("LOG-003"))
    assert [row["id"] for row in fold.rows] == ["T-decoupling"]  # not A+B
    assert fold.source.id == "LOG-002"


def test_an_explicit_empty_list_clears(tmp_path):
    project = _project(
        tmp_path,
        "defaults: { type: log }\n"
        "items:\n"
        "  - id: LOG-001\n"
        "    summary: Work list.\n"
        "    date: 2026-08-30\n"
        "    tasks:\n"
        f"{THERMAL}"
        "  - id: LOG-002\n"
        "    summary: Done with the list.\n"
        "    date: 2026-09-01\n"
        "    follows: [LOG-001]\n"
        "    tasks: []\n"
        "  - id: LOG-003\n"
        "    summary: Nothing after the clear.\n"
        "    date: 2026-09-02\n"
        "    follows: [LOG-002]\n",
    )
    assert not project.errors
    (fold,) = chains.fold_tasks(project, project.item_by_id("LOG-003"))
    assert fold.rows == []  # declared and cleared -- not "never declared"
    assert fold.source.id == "LOG-002"
    assert not fold.ambiguous


def test_inherited_defaults_do_not_declare(tmp_path):
    """Rule 1: a file's `defaults:` hands `tasks:` down to every entry, but
    no entry declared anything -- the fold sees no list, in either sense."""
    project = _project(
        tmp_path,
        "defaults:\n"
        "  type: log\n"
        "  tasks:\n"
        "    - {id: T-thermal-model, text: Model worst-case copper temperature., state: open}\n"
        "items:\n"
        "  - id: LOG-001\n"
        "    summary: Inherits the default list.\n"
        "    date: 2026-08-30\n"
        "  - id: LOG-002\n"
        "    summary: Inherits it too.\n"
        "    date: 2026-09-01\n"
        "    follows: [LOG-001]\n",
    )
    assert not project.errors
    head = project.item_by_id("LOG-001")
    assert "tasks" in head.fields  # the value is there...
    assert "tasks" in head.inherited_fields  # ...but nobody declared it
    (fold,) = chains.fold_tasks(project, head)
    assert fold.rows is None
    assert fold.source is None
    assert not fold.ambiguous


# ------------------------------------------------- fold: ambiguity, rule 3


def _fork_and_merge(tmp_path, tasks_002, tasks_003, tasks_004=None):
    """LOG-001 -> {LOG-002, LOG-003} -> LOG-004; each `tasks_00x` is the
    `tasks:` block (or None for silent) written on that entry."""

    def block(text):
        return f"    tasks:\n{text}" if text is not None else ""

    return _project(
        tmp_path,
        "defaults: { type: log }\n"
        "items:\n"
        "  - id: LOG-001\n"
        "    summary: Split.\n"
        "    date: 2026-08-30\n"
        "  - id: LOG-002\n"
        "    summary: One way.\n"
        "    date: 2026-09-01\n"
        "    follows: [LOG-001]\n"
        f"{block(tasks_002)}"
        "  - id: LOG-003\n"
        "    summary: The other way.\n"
        "    date: 2026-09-02\n"
        "    follows: [LOG-001]\n"
        f"{block(tasks_003)}"
        "  - id: LOG-004\n"
        "    summary: The merge.\n"
        "    date: 2026-09-03\n"
        "    follows: [LOG-002, LOG-003]\n"
        f"{block(tasks_004)}",
    )


def test_equal_lists_at_equal_distance_are_agreement(tmp_path):
    project = _fork_and_merge(tmp_path, DECOUPLING, DECOUPLING)
    (fold,) = chains.fold_tasks(project, project.item_by_id("LOG-004"))
    assert not fold.ambiguous
    assert [row["id"] for row in fold.rows] == ["T-decoupling"]


def test_differing_equal_near_declarations_are_ambiguous(tmp_path):
    """Rule 3: the silent merge has two equally-near parents and they
    disagree -- there is no single list, and the machine-readable state here
    is what H7 prints as "task reconciliation required"."""
    project = _fork_and_merge(tmp_path, THERMAL, DECOUPLING)
    (fold,) = chains.fold_tasks(project, project.item_by_id("LOG-004"))
    assert fold.ambiguous
    assert fold.rows is None
    assert fold.source is None


def test_a_merge_declaring_its_own_list_is_the_reconciliation(tmp_path):
    project = _fork_and_merge(tmp_path, THERMAL, DECOUPLING, THERMAL + DECOUPLING)
    (fold,) = chains.fold_tasks(project, project.item_by_id("LOG-004"))
    assert not fold.ambiguous
    assert [row["id"] for row in fold.rows] == ["T-thermal-model", "T-decoupling"]
    assert fold.source.id == "LOG-004"


# ------------------------------------------------- fold: the fork, rule 4


def test_a_fork_returns_one_labelled_list_per_tip_and_never_a_union(tmp_path):
    project = _project(
        tmp_path,
        "defaults: { type: log }\n"
        "items:\n"
        "  - id: LOG-001\n"
        "    summary: Common ancestor with the list.\n"
        "    date: 2026-08-30\n"
        "    tasks:\n"
        f"{THERMAL}"
        "  - id: LOG-002\n"
        "    summary: Replaced it on this branch.\n"
        "    date: 2026-09-01\n"
        "    follows: [LOG-001]\n"
        "    tasks:\n"
        f"{DECOUPLING}"
        "  - id: LOG-003\n"
        "    summary: Silent on the other branch.\n"
        "    date: 2026-09-02\n"
        "    follows: [LOG-001]\n",
    )
    assert not project.errors
    folds = chains.fold_tasks(project, project.item_by_id("LOG-001"))
    assert [fold.tip.id for fold in folds] == ["LOG-002", "LOG-003"]
    by_tip = {fold.tip.id: fold for fold in folds}
    # Each tip's own backward fold: the ancestor's list preserved where
    # silent...
    assert [row["id"] for row in by_tip["LOG-003"].rows] == ["T-thermal-model"]
    assert by_tip["LOG-003"].source.id == "LOG-001"
    # ...and the nearest declaration where it declared.
    assert [row["id"] for row in by_tip["LOG-002"].rows] == ["T-decoupling"]
    assert by_tip["LOG-002"].source.id == "LOG-002"
    # No entry anywhere carries both: no union, no single global list.
    for fold in folds:
        assert {"T-thermal-model", "T-decoupling"} != {
            row["id"] for row in fold.rows
        }
    # Asked from any entry of the thread, the same two labelled lists.
    folds2 = chains.fold_tasks(project, project.item_by_id("LOG-002"))
    assert [f.tip.id for f in folds2] == ["LOG-002", "LOG-003"]


# ----------------------------------------- the `on_change: log` guarantee


def test_ticking_a_task_moves_the_history_digest_not_the_content(tmp_path):
    """The byte this whole design leans on, from both sides: a tick is an
    event history must see (`semantic_digest` changes), and it is not
    content (`content_hash` and the baseline diff do not move)."""
    project = _project(tmp_path, _head_with_tasks())
    assert not project.errors
    digest_before = history.semantic_digest(project.item_by_id("LOG-001"))
    hash_before = project.item_by_id("LOG-001").content_hash

    stamped = lifecycle.stamp(project, kind="revision", name="rev-a")
    assert stamped.status == "stamped"

    _edit(tmp_path, "state: open", "state: done")
    project2 = _load(tmp_path)
    assert not project2.errors

    assert (
        history.semantic_digest(project2.item_by_id("LOG-001")) != digest_before
    ), "history must see a tick -- semantic_digest is the history digest"
    assert (
        project2.item_by_id("LOG-001").content_hash == hash_before
    ), "a tick must stay out of content_hash -- that is what `on_change: log` is for"
    diff = lifecycle.diff_against(
        project2, lifecycle.load_baseline(project2, "rev-a"), write=False
    )
    assert diff.changed == []
    assert diff.added == []
    assert diff.removed == []


# ----------------------------------------------- validation (validate_items)


def test_duplicate_task_id_within_a_list_is_an_error(tmp_path):
    project = _project(
        tmp_path,
        "defaults: { type: log }\n"
        "items:\n"
        "  - id: LOG-001\n"
        "    summary: Two rows, one id.\n"
        "    date: 2026-08-30\n"
        "    tasks:\n"
        f"{THERMAL}{THERMAL}",
    )
    hits = _errors_containing(project, "T-thermal-model", "unique")
    assert len(hits) == 1, [d.message for d in project.errors]
    assert "tasks[1]" in hits[0].message


def test_unknown_task_state_is_an_error(tmp_path):
    project = _project(
        tmp_path,
        "defaults: { type: log }\n"
        "items:\n"
        "  - id: LOG-001\n"
        "    summary: A state outside the vocabulary.\n"
        "    date: 2026-08-30\n"
        "    tasks:\n"
        "      - {id: T-thermal-model, text: Model it., state: closed}\n",
    )
    hits = _errors_containing(project, "closed", "open, done, dropped")
    assert len(hits) == 1, [d.message for d in project.errors]
    assert "tasks[0].state" in hits[0].message


def test_a_known_task_state_builds_clean(tmp_path):
    project = _project(
        tmp_path,
        "defaults: { type: log }\n"
        "items:\n"
        "  - id: LOG-001\n"
        "    summary: Every state word.\n"
        "    date: 2026-08-30\n"
        "    tasks:\n"
        "      - {id: T-a, text: One., state: open}\n"
        "      - {id: T-b, text: Two., state: done}\n"
        "      - {id: T-c, text: Three., state: dropped}\n",
    )
    assert not project.errors
    (fold,) = chains.fold_tasks(project, project.item_by_id("LOG-001"))
    assert [row["state"] for row in fold.rows] == ["open", "done", "dropped"]


def test_a_task_written_as_a_bare_string_is_a_shape_error(tmp_path):
    project = _project(
        tmp_path,
        "defaults: { type: log }\n"
        "items:\n"
        "  - id: LOG-001\n"
        "    summary: Not a mapping.\n"
        "    date: 2026-08-30\n"
        "    tasks: [model the copper temperature]\n",
    )
    hits = _errors_containing(project, "is not a task")
    assert len(hits) == 1, [d.message for d in project.errors]


def test_a_scalar_tasks_is_the_loaders_error(tmp_path):
    project = _project(
        tmp_path,
        "defaults: { type: log }\n"
        "items:\n"
        "  - id: LOG-001\n"
        "    summary: A scalar where a list belongs.\n"
        "    date: 2026-08-30\n"
        "    tasks: model the copper temperature\n",
    )
    hits = _errors_containing(project, "tasks", "write it as a list")
    assert len(hits) == 1, [d.message for d in project.errors]
