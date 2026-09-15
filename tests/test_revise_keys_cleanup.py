"""Surrogate-keys subtractive cleanup (docs/design/keys.md §4).

The prefix-rename path no longer rewrites bare references, no longer
relabels the id ledger, and no longer remaps baseline/seal record ids. In
its place: apply() runs the writable-load key pipeline (mint, link/check
expansion, follows freeze) inside its own transaction, refuses with
file:line if a structured reference to an affected id is still bare
afterwards, and refreshes composite display halves after the rename.
A dry run simulates that whole pipeline on a throwaway copy of the tree.
"""

from __future__ import annotations

import os

import pytest
from conftest import write_project_config

from refdes import build as build_mod
from refdes import former_ids, lifecycle, parse, revise
from refdes import keys as keys_mod
from refdes.schema import load_project

KEYS_SCHEMA = (
    "site: { title: T, out: _site }\n"
    "link_types:\n"
    "  constrained_by: { inverse: constrains, label: \"Constrained by\" }\n"
    "types:\n"
    "  constraint:\n"
    "    prefix: CON\n"
    "    fields:\n"
    "      text:  { type: text, required: true }\n"
    "      limit: { type: limit, required: true }\n"
    "  decision:\n"
    "    prefix: DEC\n"
    "    fields:\n"
    "      title: { type: text, required: true }\n"
    "      checks: { type: checks }\n"
    "    links:\n"
    "      constrained_by: [constraint]\n"
)


@pytest.fixture
def keyed_project(tmp_path):
    """A project whose references are still bare -- the state a real project
    sits in between writable loads, and the state a prefix rename now has to
    cope with by expanding first, not by rewriting text."""
    write_project_config(tmp_path, KEYS_SCHEMA)
    items = tmp_path / "items"
    items.mkdir()
    (items / "con.yaml").write_text(
        "defaults:\n  type: constraint\n  prefix: CON\n"
        "items:\n"
        "  - id: CON-001\n    text: Board power density\n    limit: \"<= 0.15 W/in^2\"\n",
        encoding="utf-8",
    )
    (items / "dec.md").write_text(
        "---\n"
        "id: DEC-001\n"
        "type: decision\n"
        "title: Regulator topology\n"
        "constrained_by: [CON-001]\n"
        "checks:\n"
        "  - value: P_dens\n"
        "    against: CON-001\n"
        "---\n\n"
        "```calc\nP_dens : W/in^2 = 0.1 W/in^2\n```\n",
        encoding="utf-8",
    )
    return tmp_path


def _tree_texts(root):
    texts = {}
    for name in sorted(os.listdir(root / "items")):
        path = root / "items" / name
        texts[f"items/{name}"] = path.read_text(encoding="utf-8")
    return texts


def test_prefix_rename_expands_then_moves_display_halves(keyed_project):
    """The core new path: bare references are expanded to composites by the
    load pipeline (not text-rewritten), the rename moves the id lines, and
    the composites' display halves refresh. A clean reload+build proves
    every reference still resolves."""
    result = revise.apply(str(keyed_project), revise.Mapping(prefixes={"CON": "BND"}))
    assert result.ok, result.errors
    assert result.id_changes == {"CON-001": "BND-001"}

    con = (keyed_project / "items" / "con.yaml").read_text(encoding="utf-8")
    assert "id: BND-001" in con
    dec = (keyed_project / "items" / "dec.md").read_text(encoding="utf-8")
    assert "constrained_by: [BND-001@" in dec
    assert "against: BND-001@" in dec
    assert "CON-001" not in dec  # no stale display half left behind

    project = load_project(config_path=str(keyed_project / "refdes-project.yaml"))
    parse.load_items(project)
    build_mod.build(project, seal_write=False, reseal=False, accept_board_move=False)
    assert not project.errors, [str(d) for d in project.errors]


def test_prefix_rename_never_touches_the_id_ledger(keyed_project):
    (keyed_project / ".refdes").mkdir(exist_ok=True)
    (keyed_project / ".refdes" / "ids.yaml").write_text(
        "burned:\n  CON: 1\nallocated: []\n", encoding="utf-8"
    )
    result = revise.apply(str(keyed_project), revise.Mapping(prefixes={"CON": "BND"}))
    assert result.ok, result.errors
    ledger = (keyed_project / ".refdes" / "ids.yaml").read_text(encoding="utf-8")
    assert "CON: 1" in ledger and "BND" not in ledger


def test_prefix_rename_carries_hashes_and_seals_under_stable_keys(keyed_project):
    """Keyed baseline and seal records keep their record keys across the
    rename -- only the hash moves -- and the diff reports the pair as
    relabelled, not removed+added."""
    project = load_project(config_path=str(keyed_project / "refdes-project.yaml"))
    parse.load_items(project)
    keys_mod.mint_missing(project, write=True)  # what a writable load does
    build_mod.build(project, seal_write=True)
    assert not project.errors
    lifecycle.stamp(project, kind="revision", name="rev-a")

    result = revise.apply(str(keyed_project), revise.Mapping(prefixes={"CON": "BND"}))
    assert result.ok, result.errors

    project2 = load_project(config_path=str(keyed_project / "refdes-project.yaml"))
    parse.load_items(project2)
    build_mod.build(project2, seal_write=False, reseal=False, accept_board_move=False)
    assert not project2.errors, [str(d) for d in project2.errors]
    assert project2.seal_violations == []

    baseline = lifecycle.load_baseline(project2, "rev-a")
    diff = lifecycle.diff_against(project2, baseline)
    assert diff.removed == [] and diff.added == []
    keyed = [r for r in diff.relabelled if r[0] == "CON-001"]
    assert keyed == [("CON-001", "BND-001", project2.item_by_id("BND-001").key)]


def test_dry_run_simulates_the_pipeline_and_writes_nothing(keyed_project, capsys):
    """A dry run reports the mint/expand the real run would perform -- on an
    untouched tree."""
    before = _tree_texts(keyed_project)
    result = revise.apply(
        str(keyed_project), revise.Mapping(prefixes={"CON": "BND"}), dry_run=True
    )
    assert result.ok, result.errors
    assert result.expansions, "dry run must report what the real run would expand"
    assert any("constrained_by" in e for e in result.expansions)
    assert any("against" in e for e in result.expansions)
    assert _tree_texts(keyed_project) == before


# ------------------------------------------------------------- the bare-ref guard


def _no_mint(monkeypatch):
    """Sabotage the ensure pipeline's first step: with nothing minted, no
    bare reference can expand, so the guard is left facing exactly the
    references it exists to refuse. The real-world survivor of this shape is
    `checks:` inherited from defaults: (docs/design/keys.md's disclosed
    expansion gap); this is the same state, reached deterministically."""
    monkeypatch.setattr(keys_mod, "mint_missing", lambda project, write=True: [])


def test_rename_refuses_over_a_bare_reference_that_survives_expansion(keyed_project, monkeypatch):
    _no_mint(monkeypatch)
    before = _tree_texts(keyed_project)
    result = revise.apply(str(keyed_project), revise.Mapping(prefixes={"CON": "BND"}))
    assert not result.ok
    assert any(
        "items/dec.md" in e and "constrained_by" in e and "CON-001" in e
        for e in result.errors
    ), result.errors
    assert any("items/dec.md" in e and "check against" in e for e in result.errors), result.errors
    assert _tree_texts(keyed_project) == before


def test_dry_run_refuses_over_a_surviving_bare_reference(keyed_project, monkeypatch):
    _no_mint(monkeypatch)
    before = _tree_texts(keyed_project)
    result = revise.apply(
        str(keyed_project), revise.Mapping(prefixes={"CON": "BND"}), dry_run=True
    )
    assert not result.ok
    assert any("items/dec.md" in e and "constrained_by" in e for e in result.errors)
    assert _tree_texts(keyed_project) == before


def test_guard_ignores_references_the_rename_does_not_move(keyed_project, monkeypatch):
    """A bare reference to an item whose id the rename does not touch is not
    a blocker -- the guard is about what this rename would strand, not about
    bare references in general."""
    _no_mint(monkeypatch)
    result = revise.apply(str(keyed_project), revise.Mapping(prefixes={"DEC": "ADR"}))
    assert result.ok, result.errors
    assert result.id_changes == {"DEC-001": "ADR-001"}


# ------------------------------------------------------- former-ids propose keys


def _keyed_baseline_project(tmp_path):
    write_project_config(
        tmp_path,
        "site: { title: T, out: _site }\n"
        "types:\n"
        "  bound:\n"
        "    prefix: BND\n"
        "    fields:\n"
        "      text:  { type: text, required: true }\n"
        "      limit: { type: limit, required: true }\n",
    )
    (tmp_path / "items").mkdir()
    (tmp_path / "items" / "i.yaml").write_text(
        "defaults:\n  type: bound\n  prefix: BND\n"
        "items:\n"
        "  - id: BND-001\n    text: Board power density\n    limit: \"<= 0.15 W/in^2\"\n",
        encoding="utf-8",
    )
    return tmp_path


def _key_keyed_baseline(root):
    project = load_project(config_path=str(root / "refdes-project.yaml"))
    parse.load_items(project)
    keys_mod.mint_missing(project, write=True)
    build_mod.build(project, seal_write=False, reseal=False)
    lifecycle.stamp(project, kind="revision", name="rev-a")
    baseline = lifecycle.load_baseline(project, "rev-a")
    conversion = keys_mod.plan_surrogate_storage(project, baseline.items, {})
    lifecycle._save_baseline_file(
        project,
        {
            "kind": baseline.kind,
            "name": baseline.name,
            "stamped_at": baseline.stamped_at,
            "stamped_by": baseline.stamped_by,
            "refdes_version": baseline.refdes_version,
            "items": conversion.baseline_items,
        },
    )


def test_propose_returns_exact_candidates_from_a_keyed_baseline(tmp_path):
    """A keyed baseline proves the old/new pairing through the key itself:
    propose returns it exact, with no similarity inference involved."""
    root = _keyed_baseline_project(tmp_path)
    _key_keyed_baseline(root)
    result = revise.apply(str(root), revise.Mapping(prefixes={"BND": "LIM"}))
    assert result.ok, result.errors

    project = load_project(config_path=str(root / "refdes-project.yaml"))
    parse.load_items(project)
    build_mod.build(project, seal_write=False, reseal=False)
    candidates = former_ids.propose(project)
    assert [c.old_id for c in candidates] == ["BND-001"]
    assert candidates[0].new_id == "LIM-001"
    assert candidates[0].exact is True
    assert candidates[0].confidence == 1.0


def test_propose_still_scores_a_keyless_legacy_baseline(tmp_path):
    root = _keyed_baseline_project(tmp_path)
    project = load_project(config_path=str(root / "refdes-project.yaml"))
    parse.load_items(project)
    build_mod.build(project, seal_write=False, reseal=False)
    lifecycle.stamp(project, kind="revision", name="rev-a")

    (root / "items" / "i.yaml").write_text(
        "defaults:\n  type: bound\n  prefix: BND\n"
        "items:\n"
        "  - id: BND-002\n    text: Board power density\n    limit: \"<= 0.15 W/in^2\"\n",
        encoding="utf-8",
    )
    project2 = load_project(config_path=str(root / "refdes-project.yaml"))
    parse.load_items(project2)
    build_mod.build(project2, seal_write=False, reseal=False)
    candidates = former_ids.propose(project2)
    assert [c.old_id for c in candidates] == ["BND-001"]
    assert candidates[0].new_id == "BND-002"
    assert candidates[0].exact is False
