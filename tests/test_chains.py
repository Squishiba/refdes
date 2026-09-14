"""Threads Phase 2b: the `follows:` chain module.

docs/design/threads.md §3 (the lazy walk, `resolve_current`'s per-field fold,
"Branching's effect on current") and §6 (forks are legal info, merges close
them, cycles are hard errors). The schema here declares `follows:` by hand --
`hardware@3` does not declare it yet (that's the standard-layer phase) -- so
every project in this file is the "any project whose schema declares it" case
§7 describes.
"""

from __future__ import annotations

import pytest
from conftest import write_project_config

from refdes import build as build_mod
from refdes import chains, keys as keys_mod, parse
from refdes.schema import load_project

CHAIN_SCHEMA = """\
site: { title: Chain Test, out: _site }
id: { width: 3, ledger: .refdes/ids.yaml }
link_types:
  follows: { inverse: followed_by, label: Follows }
types:
  log:
    prefix: LOG
    label: Log entry
    plural: Log entries
    fields:
      summary: { type: text, required: true }
      status:  { type: enum, choices: [proposed, accepted, on_hold] }
    links:
      follows: [log]
"""


def _project(tmp_path, items_yaml):
    write_project_config(tmp_path, CHAIN_SCHEMA)
    items = tmp_path / "items"
    items.mkdir()
    (items / "log.yaml").write_text(items_yaml, encoding="utf-8")
    project = load_project(config_path=str(tmp_path / "refdes-project.yaml"))
    parse.load_items(project)
    keys_mod.mint_missing(project)
    build_mod.build(project)
    return project


def _by_id(project, display_id):
    return project.item_by_id(display_id)


LINEAR = (
    "defaults: { type: log }\n"
    "items:\n"
    "  - id: LOG-001\n    summary: First.\n    status: proposed\n"
    "  - id: LOG-002\n    summary: Second.\n    follows: [LOG-001]\n"
    "  - id: LOG-003\n    summary: Third.\n    status: accepted\n    follows: [LOG-002]\n"
)


def test_linear_chain_tips_from_head_is_the_last_entry(tmp_path):
    project = _project(tmp_path, LINEAR)
    head = _by_id(project, "LOG-001")
    tip = chains.tips(project, head)
    assert [i.id for i in tip] == ["LOG-003"]
    assert not project.errors
    assert not project.infos


def test_resolve_current_returns_the_latest_declared_value(tmp_path):
    project = _project(tmp_path, LINEAR)
    assert chains.resolve_current(project, _by_id(project, "LOG-001"), "status") == "accepted"
    # Starting mid-chain still folds the whole forward reach.
    assert chains.resolve_current(project, _by_id(project, "LOG-002"), "status") == "accepted"


def test_an_entry_omitting_the_field_does_not_clear_it(tmp_path):
    """LOG-002 declares no status; the value set by LOG-001 must survive it,
    and LOG-003's own declaration still wins over both."""
    project = _project(tmp_path, LINEAR)
    assert "status" not in _by_id(project, "LOG-002").fields
    assert chains.resolve_current(project, _by_id(project, "LOG-002"), "summary") == "Third."
    assert chains.resolve_current(project, _by_id(project, "LOG-001"), "status") == "accepted"
    # Nothing in the reachable chain ever declares this field.
    assert chains.resolve_current(project, _by_id(project, "LOG-001"), "author") is None


FORK = (
    "defaults: { type: log }\n"
    "items:\n"
    "  - id: LOG-001\n    summary: Head.\n    status: proposed\n"
    "  - id: LOG-002\n    summary: Branch A.\n    follows: [LOG-001]\n"
    "  - id: LOG-003\n    summary: Branch B.\n    follows: [LOG-001]\n"
)


def test_fork_is_undefined_and_reported_once(tmp_path):
    project = _project(tmp_path, FORK)
    head = _by_id(project, "LOG-001")
    assert sorted(i.id for i in chains.tips(project, head)) == ["LOG-002", "LOG-003"]
    # An unmerged fork is never "settled" (§3), even though a value exists upstream.
    assert chains.resolve_current(project, head, "status") is None

    assert not project.errors
    fork_infos = [d for d in project.infos if "has forked" in d.message]
    assert len(fork_infos) == 1  # one per forked entry, not one per successor
    assert "LOG-002" in fork_infos[0].message and "LOG-003" in fork_infos[0].message
    assert "append an entry declaring follows: [both tips]" in fork_infos[0].message


MERGED = FORK + (
    "  - id: LOG-004\n    summary: Reconciled.\n    status: accepted\n"
    "    follows: [LOG-002, LOG-003]\n"
)


def test_a_merge_entry_closes_the_fork(tmp_path):
    project = _project(tmp_path, MERGED)
    for start in ("LOG-001", "LOG-002", "LOG-003"):
        tip = chains.tips(project, _by_id(project, start))
        assert [i.id for i in tip] == ["LOG-004"]
    assert chains.resolve_current(project, _by_id(project, "LOG-001"), "status") == "accepted"
    assert not [d for d in project.infos if "has forked" in d.message]
    assert not project.errors


def test_value_comes_from_the_nearest_declaring_entry_after_a_merge(tmp_path):
    """The merge entry and both parents are silent on status, so the fold
    keeps walking back to the nearest entry that does declare it."""
    project = _project(
        tmp_path,
        FORK
        + "  - id: LOG-004\n    summary: Reconciled.\n    follows: [LOG-002, LOG-003]\n",
    )
    assert chains.resolve_current(project, _by_id(project, "LOG-001"), "status") == "proposed"


def test_equal_distance_conflicting_values_are_ambiguous(tmp_path):
    project = _project(
        tmp_path,
        "defaults: { type: log }\n"
        "items:\n"
        "  - id: LOG-001\n    summary: Head.\n"
        "  - id: LOG-002\n    summary: A.\n    status: accepted\n    follows: [LOG-001]\n"
        "  - id: LOG-003\n    summary: B.\n    status: on_hold\n    follows: [LOG-001]\n"
        "  - id: LOG-004\n    summary: Merge, silent on status.\n"
        "    follows: [LOG-002, LOG-003]\n",
    )
    assert chains.resolve_current(project, _by_id(project, "LOG-001"), "status") is None
    # A nearer declaration still wins outright, ambiguity aside.
    summary = chains.resolve_current(project, _by_id(project, "LOG-001"), "summary")
    assert summary == "Merge, silent on status."


CYCLE = (
    "defaults: { type: log }\n"
    "items:\n"
    "  - id: LOG-001\n    summary: First.\n    follows: [LOG-003]\n"
    "  - id: LOG-002\n    summary: Second.\n    follows: [LOG-001]\n"
    "  - id: LOG-003\n    summary: Third.\n    follows: [LOG-002]\n"
)


def test_a_cycle_is_one_error_naming_the_cycle(tmp_path):
    project = _project(tmp_path, CYCLE)
    cycle_errors = [d for d in project.errors if "follows cycle" in d.message]
    assert len(cycle_errors) == 1  # once for the cycle, not once per member
    assert "LOG-001 -> LOG-003 -> LOG-002 -> LOG-001" in cycle_errors[0].message


def test_resolve_current_terminates_on_a_cycle(tmp_path):
    project = _project(tmp_path, CYCLE)
    # Every node has a successor, so there is no tip and no fold -- but the
    # walk must return, not spin.
    assert chains.resolve_current(project, _by_id(project, "LOG-001"), "status") is None
    assert chains.tips(project, _by_id(project, "LOG-001")) == []


def test_an_id_less_continuation_participates_and_is_named_by_key(tmp_path):
    project = _project(
        tmp_path,
        "defaults: { type: log }\n"
        "items:\n"
        "  - id: LOG-001\n    summary: Head.\n"
        "  - summary: Id-less A.\n    follows: [LOG-001]\n"
        "  - summary: Id-less B.\n    follows: [LOG-001]\n",
    )
    idless = [i for i in project.items.values() if not i.id]
    assert len(idless) == 2
    head = _by_id(project, "LOG-001")
    assert sorted(i.key for i in chains.tips(project, head)) == sorted(i.key for i in idless)

    fork = [d for d in project.infos if "has forked" in d.message]
    assert len(fork) == 1
    for entry in idless:
        assert entry.key in fork[0].message  # named by key, having no display id


def test_a_project_with_no_follows_anywhere_reports_nothing(tmp_path):
    project = _project(
        tmp_path,
        "defaults: { type: log }\n"
        "items:\n  - id: LOG-001\n    summary: A lone entry.\n",
    )
    assert project.diagnostics == []
    assert chains.build_graph(project) == ({}, {})


def test_an_unresolvable_follows_target_is_not_an_edge(tmp_path):
    """resolve_links already errors on the dangling target; the walk adds a
    second, independent error for it but must not invent an edge or crash."""
    project = _project(
        tmp_path,
        "defaults: { type: log }\n"
        "items:\n  - id: LOG-001\n    summary: Dangling.\n    follows: [LOG-999]\n",
    )
    assert any("LOG-999" in d.message for d in project.errors)
    preds, succs = chains.build_graph(project)
    assert preds == {} and succs == {}


def test_resolve_current_from_an_unknown_start_is_none(tmp_path):
    project = _project(tmp_path, LINEAR)
    assert chains.resolve_current(project, "LOG-999", "status") is None
    assert chains.tips(project, "LOG-999") == []


def test_start_accepts_a_display_id_or_an_item(tmp_path):
    project = _project(tmp_path, LINEAR)
    by_id = chains.resolve_current(project, "LOG-001", "status")
    by_item = chains.resolve_current(project, _by_id(project, "LOG-001"), "status")
    assert by_id == by_item == "accepted"


@pytest.mark.parametrize("field", ["status", "summary"])
def test_a_fork_never_folds_to_a_value(tmp_path, field):
    """Sabotage guard for §3: with two reachable tips the answer is undefined
    whatever the field, because a fork is not yet a single conclusion."""
    project = _project(tmp_path, FORK)
    assert chains.resolve_current(project, _by_id(project, "LOG-001"), field) is None
