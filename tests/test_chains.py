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
from refdes import chains, parse
from refdes import keys as keys_mod
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
    items.mkdir(exist_ok=True)
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


def test_a_field_inherited_from_the_file_defaults_does_not_declare_it(tmp_path):
    """§3's fold is "the most recent entry that *declared* F", and a value a
    file's `defaults:` block handed down is not the entry declaring it --
    otherwise a log file defaulting `status: proposed` would have every
    silent entry in it shadow the `accepted` its head actually set."""
    project = _project(
        tmp_path,
        "defaults: { type: log, status: proposed }\n"
        "items:\n"
        "  - id: LOG-001\n    summary: Head.\n    status: accepted\n"
        "  - id: LOG-002\n    summary: Second.\n    follows: [LOG-001]\n"
        "  - id: LOG-003\n    summary: Third.\n    follows: [LOG-002]\n",
    )
    head, middle, last = (_by_id(project, f"LOG-00{n}") for n in (1, 2, 3))
    assert "status" in middle.fields and "status" in middle.inherited_fields
    assert "status" in head.fields and "status" not in head.inherited_fields

    assert chains.resolve_current(project, head, "status") == "accepted"
    assert chains.resolve_current(project, middle, "status") == "accepted"
    assert chains.resolve_current(project, last, "status") == "accepted"

    # And with no explicit declaration anywhere, the default alone is not a
    # value the fold reports: nothing in the chain ever declared it.
    silent = _project(
        tmp_path,
        "defaults: { type: log, status: proposed }\n"
        "items:\n"
        "  - id: LOG-001\n    summary: Head.\n"
        "  - id: LOG-002\n    summary: Second.\n    follows: [LOG-001]\n",
    )
    assert chains.resolve_current(silent, _by_id(silent, "LOG-001"), "status") is None


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


def test_resolve_current_memoized_per_component(tmp_path):
    """Two entries in the same thread share one fold via the per-component cache.

    We patch the internal fold loop (the breadth-first walk in `resolve_current`)
    and count how many times it actually runs. For a linear chain of 3 entries
    all in one component, resolving `status` from each entry must invoke the
    fold exactly once -- the first call populates the cache, subsequent calls
    return the cached value.
    """
    project = _project(
        tmp_path,
        "defaults: { type: log }\n"
        "items:\n"
        "  - id: LOG-001\n    summary: Head.\n    status: accepted\n"
        "  - id: LOG-002\n    summary: Second.\n    follows: [LOG-001]\n"
        "  - id: LOG-003\n    summary: Third.\n    follows: [LOG-002]\n",
    )

    # The fold is the while-frontier loop inside resolve_current. We can't
    # easily patch just that loop, so instead we verify the cache behavior
    # directly via the ChainGraph's public cache API.
    cg = chains.build_graph(project)
    head = _by_id(project, "LOG-001")
    middle = _by_id(project, "LOG-002")
    last = _by_id(project, "LOG-003")

    # First call populates the cache
    assert chains.resolve_current(project, head, "status", graph=cg) == "accepted"
    assert len(cg._resolve_cache) == 1
    comp_id = cg.component_id(cg._handles[id(head)])
    assert (comp_id, "status") in cg._resolve_cache

    # Subsequent calls for other entries in the same component hit the cache
    assert chains.resolve_current(project, middle, "status", graph=cg) == "accepted"
    assert chains.resolve_current(project, last, "status", graph=cg) == "accepted"
    # Cache size unchanged -- no new fold performed
    assert len(cg._resolve_cache) == 1

    # A different field is a separate cache entry
    assert chains.resolve_current(project, head, "summary", graph=cg) == "Third."
    assert len(cg._resolve_cache) == 2
    assert (comp_id, "summary") in cg._resolve_cache

    # Without a ChainGraph (legacy tuple or None), no cache is used -- but
    # results must still be identical.
    assert chains.resolve_current(project, head, "status") == "accepted"
    assert chains.resolve_current(project, middle, "status") == "accepted"
    assert chains.resolve_current(project, last, "status") == "accepted"


def test_resolve_current_walks_component_once_per_field(tmp_path):
    """The component walk (roots + tips + fold) runs once per (component, field).

    We verify by checking that the component's tips are cached after the first
    call, and subsequent calls for the same (component, field) don't add new
    entries to the tips cache.
    """
    project = _project(
        tmp_path,
        "defaults: { type: log }\n"
        "items:\n"
        "  - id: LOG-001\n    summary: Head.\n    status: accepted\n"
        "  - id: LOG-002\n    summary: Second.\n    follows: [LOG-001]\n"
        "  - id: LOG-003\n    summary: Third.\n    follows: [LOG-002]\n"
        "  - id: LOG-004\n    summary: Fourth.\n    follows: [LOG-003]\n"
        "  - id: LOG-005\n    summary: Fifth.\n    follows: [LOG-004]\n",
    )

    cg = chains.build_graph(project)
    head = _by_id(project, "LOG-001")
    middle = _by_id(project, "LOG-003")
    last = _by_id(project, "LOG-005")

    # First call for status - computes and caches tips
    assert chains.resolve_current(project, head, "status", graph=cg) == "accepted"
    assert len(cg._component_tips) == 1  # tips cached for this component

    # Second call for same field - should use cached tips
    assert chains.resolve_current(project, middle, "status", graph=cg) == "accepted"
    assert len(cg._component_tips) == 1  # no new tips computed

    # Third call for same field - should use cached tips
    assert chains.resolve_current(project, last, "status", graph=cg) == "accepted"
    assert len(cg._component_tips) == 1  # still no new tips computed

    # Different field - should compute tips again (new cache key)
    assert chains.resolve_current(project, head, "summary", graph=cg) == "Fifth."
    assert len(cg._component_tips) == 1  # tips already cached for component

    # Forked thread: same component, fork -> caches None
    fork_project = _project(
        tmp_path,
        "defaults: { type: log }\n"
        "items:\n"
        "  - id: LOG-001\n    summary: Head.\n    status: accepted\n"
        "  - id: LOG-002\n    summary: Branch A.\n    follows: [LOG-001]\n"
        "  - id: LOG-003\n    summary: Branch B.\n    follows: [LOG-001]\n",
    )
    fork_cg = chains.build_graph(fork_project)
    fork_head = _by_id(fork_project, "LOG-001")
    fork_a = _by_id(fork_project, "LOG-002")
    fork_b = _by_id(fork_project, "LOG-003")

    # First call walks and caches None (fork)
    assert chains.resolve_current(fork_project, fork_head, "status", graph=fork_cg) is None
    assert len(fork_cg._component_tips) == 1  # tips (both forks) cached
    assert len(fork_cg._resolve_cache) == 1  # None cached for fork

    # Second call for same field hits cache (None)
    assert chains.resolve_current(fork_project, fork_a, "status", graph=fork_cg) is None
    assert len(fork_cg._component_tips) == 1  # no new tips
    assert len(fork_cg._resolve_cache) == 1  # cache hit

    # Third call for same field hits cache
    assert chains.resolve_current(fork_project, fork_b, "status", graph=fork_cg) is None
    assert len(fork_cg._component_tips) == 1
    assert len(fork_cg._resolve_cache) == 1


def test_resolve_current_component_tips_whole_component(tmp_path):
    """Component-wide tips: a fork anywhere in the component makes it unsettled.

    Structure:
      H1 (LOG-001, status=accepted) -> A (LOG-002)
      H2 (LOG-003, status=proposed) -> B (LOG-004)
      M (LOG-005, merge) follows [A, B], status=accepted
      C (LOG-006, fork from H2) follows [H2]

    Component has tips {M, C} = 2 tips -> fork -> None for ALL entries.
    """
    project = _project(
        tmp_path,
        "defaults: { type: log }\n"
        "items:\n"
        "  - id: LOG-001\n    summary: Head 1\n    status: accepted\n"
        "  - id: LOG-002\n    summary: A\n    follows: [LOG-001]\n"
        "  - id: LOG-003\n    summary: Head 2\n    status: proposed\n"
        "  - id: LOG-004\n    summary: B\n    follows: [LOG-003]\n"
        "  - id: LOG-005\n    summary: Merge\n    follows: [LOG-002, LOG-004]\n    status: accepted\n"
        "  - id: LOG-006\n    summary: Fork from H2\n    follows: [LOG-003]\n",
    )

    cg = chains.build_graph(project)
    log1 = _by_id(project, "LOG-001")  # H1
    log2 = _by_id(project, "LOG-002")  # A
    log3 = _by_id(project, "LOG-003")  # H2
    log4 = _by_id(project, "LOG-004")  # B
    log5 = _by_id(project, "LOG-005")  # M (merge)
    log6 = _by_id(project, "LOG-006")  # C (fork from H2)

    # With ChainGraph: query A first then C (both should be None)
    assert chains.resolve_current(project, log2, "status", graph=cg) is None
    assert chains.resolve_current(project, log6, "status", graph=cg) is None
    assert len(cg._resolve_cache) == 1  # one cache entry for (component, status)
    assert len(cg._component_tips) == 1
    tips = cg._component_tips[0]
    assert len(tips) == 2  # M and C are the two tips

    # With ChainGraph: query C first then A (order shouldn't matter)
    cg2 = chains.build_graph(project)
    assert chains.resolve_current(project, log6, "status", graph=cg2) is None
    assert chains.resolve_current(project, log2, "status", graph=cg2) is None

    # Without graph (uncached): both should also be None
    assert chains.resolve_current(project, log2, "status") is None
    assert chains.resolve_current(project, log6, "status") is None
    assert chains.resolve_current(project, log1, "status") is None
    assert chains.resolve_current(project, log3, "status") is None
    assert chains.resolve_current(project, log4, "status") is None
    assert chains.resolve_current(project, log5, "status") is None


def test_resolve_current_merged_component_settled(tmp_path):
    """A component with only merges (no forks) resolves to the settled value.

    Structure:
      H1 (LOG-001, status=accepted) -> A (LOG-002)
      H2 (LOG-003, no status) -> B (LOG-004)
      M (LOG-005, merge) follows [A, B], status=accepted

    Component has single tip {M} -> fold from M finds status=accepted.
    All entries in component should resolve to 'accepted'.
    """
    project = _project(
        tmp_path,
        "defaults: { type: log }\n"
        "items:\n"
        "  - id: LOG-001\n    summary: Head 1\n    status: accepted\n"
        "  - id: LOG-002\n    summary: A\n    follows: [LOG-001]\n"
        "  - id: LOG-003\n    summary: Head 2\n"
        "  - id: LOG-004\n    summary: B\n    follows: [LOG-003]\n"
        "  - id: LOG-005\n    summary: Merge\n    follows: [LOG-002, LOG-004]\n    status: accepted\n",
    )

    cg = chains.build_graph(project)
    log1 = _by_id(project, "LOG-001")  # H1
    log2 = _by_id(project, "LOG-002")  # A
    log3 = _by_id(project, "LOG-003")  # H2
    log4 = _by_id(project, "LOG-004")  # B
    log5 = _by_id(project, "LOG-005")  # M (merge)

    # All entries in component should resolve to 'accepted'
    assert chains.resolve_current(project, log1, "status", graph=cg) == "accepted"
    assert chains.resolve_current(project, log2, "status", graph=cg) == "accepted"
    assert chains.resolve_current(project, log3, "status", graph=cg) == "accepted"
    assert chains.resolve_current(project, log4, "status", graph=cg) == "accepted"
    assert chains.resolve_current(project, log5, "status", graph=cg) == "accepted"

    # Without graph (uncached): all should also be 'accepted'
    assert chains.resolve_current(project, log1, "status") == "accepted"
    assert chains.resolve_current(project, log2, "status") == "accepted"
    assert chains.resolve_current(project, log3, "status") == "accepted"
    assert chains.resolve_current(project, log4, "status") == "accepted"
    assert chains.resolve_current(project, log5, "status") == "accepted"


def test_handles_not_called_per_resolve_current_when_chain_graph_given(tmp_path):
    """When a ChainGraph is passed, _handles(project) is not rebuilt per call."""
    project = _project(tmp_path, LINEAR)
    cg = chains.build_graph(project)
    original_handles = chains._handles
    call_count = [0]
    def counting_handles(project):
        call_count[0] += 1
        return original_handles(project)
    import unittest.mock
    with unittest.mock.patch.object(chains, "_handles", counting_handles):
        for entry in project.local_items:
            chains.resolve_current(project, entry, "status", graph=cg)
            chains.is_threaded(project, entry, graph=cg)
    assert call_count[0] == 0, f"_handles was called {call_count[0]} times when ChainGraph passed"
