"""former_ids -- and: orphaned ledger allocations (finding 10 Part 2, narrower), former-ids propose command.

Split out of the original monolithic tests/test_refdes.py.
"""

from __future__ import annotations

import pytest

from refdes import build as build_mod
from refdes import cli as cli_mod
from refdes import former_ids, ids, lifecycle, parse, render
from refdes.schema import load_project

# ------------------------------------------------------------------ former_ids

FORMER_IDS_SCHEMA = (
    "site: { title: T, out: _site }\n"
    "types:\n"
    "  requirement: { prefix: REQ, fields: { text: { type: text } } }\n"
    "  decision: { prefix: DEC, fields: {}, body: {} }\n"
)


def _former_ids_project(tmp_path, items_yaml):
    (tmp_path / "refdes.yaml").write_text(FORMER_IDS_SCHEMA, encoding="utf-8")
    items = tmp_path / "items"
    items.mkdir()
    (items / "r.yaml").write_text(items_yaml, encoding="utf-8")
    return tmp_path


def _former_ids_build(root):
    project = load_project(config_path=str(root / "refdes.yaml"))
    parse.load_items(project, require_ids=False)
    build_mod.build(project, seal_write=False, reseal=False)
    return project


def test_former_ids_are_burned_so_the_allocator_never_reissues_them(tmp_path):
    root = _former_ids_project(
        tmp_path,
        "defaults: { type: requirement }\n"
        "items:\n"
        "  - id: REQ-001\n    text: Renumbered item.\n    former_ids: [REQ-050]\n"
        "  - text: Brand new, no id yet.\n",
    )
    project = load_project(config_path=str(root / "refdes.yaml"))
    parse.load_items(project, require_ids=False)
    assignments = ids.allocate(project)
    assert assignments[0][1] == "REQ-051"  # not REQ-002 -- REQ-050 stays burned


def test_former_ids_colliding_with_another_items_live_id_is_an_error(tmp_path):
    root = _former_ids_project(
        tmp_path,
        "defaults: { type: requirement }\n"
        "items:\n"
        "  - id: REQ-001\n    text: A.\n"
        "  - id: REQ-002\n    text: B.\n    former_ids: [REQ-001]\n",
    )
    project = _former_ids_build(root)
    assert any(
        "former_ids: 'REQ-001' is still a live item id" in d.message and d.item_id == "REQ-002"
        for d in project.errors
    )
    assert "REQ-001" not in project.former_ids


def test_former_ids_naming_itself_is_an_error(tmp_path):
    root = _former_ids_project(
        tmp_path,
        "defaults: { type: requirement }\n"
        "items:\n  - id: REQ-001\n    text: A.\n    former_ids: [REQ-001]\n",
    )
    project = _former_ids_build(root)
    assert any(
        "former_ids: 'REQ-001' is this item's own current id" in d.message
        for d in project.errors
    )


def test_former_ids_claimed_by_two_items_is_an_error(tmp_path):
    root = _former_ids_project(
        tmp_path,
        "defaults: { type: requirement }\n"
        "items:\n"
        "  - id: REQ-001\n    text: A.\n    former_ids: [REQ-OLD-01]\n"
        "  - id: REQ-002\n    text: B.\n    former_ids: [REQ-OLD-01]\n",
    )
    project = _former_ids_build(root)
    message = next(d.message for d in project.errors if "REQ-OLD-01" in d.message)
    assert "REQ-001" in message and "REQ-002" in message
    assert "exactly one item" in message


def test_former_ids_resolve_bracketed_reference_with_a_formerly_marker(tmp_path):
    (tmp_path / "refdes.yaml").write_text(FORMER_IDS_SCHEMA, encoding="utf-8")
    items = tmp_path / "items"
    items.mkdir()
    (items / "r.yaml").write_text(
        "defaults: { type: requirement }\n"
        "items:\n  - id: REQ-001\n    text: Renumbered.\n    former_ids: [REQ-050]\n",
        encoding="utf-8",
    )
    (items / "dec.md").write_text(
        "---\nid: DEC-001\ntype: decision\n---\n\nSee [[REQ-050]] for context.\n",
        encoding="utf-8",
    )
    project = _former_ids_build(tmp_path)
    assert not project.errors
    html = project.items["DEC-001"].body_html
    assert 'class="ref ref-former"' in html
    assert 'href="req-001.html"' in html
    assert 'data-ref="REQ-001"' in html
    assert "(formerly REQ-050)" in html


def test_former_ids_resolve_bare_reference_when_it_fits_the_bare_pattern(tmp_path):
    (tmp_path / "refdes.yaml").write_text(FORMER_IDS_SCHEMA, encoding="utf-8")
    items = tmp_path / "items"
    items.mkdir()
    (items / "r.yaml").write_text(
        "defaults: { type: requirement }\n"
        "items:\n  - id: REQ-001\n    text: Renumbered.\n    former_ids: [REQ-050]\n",
        encoding="utf-8",
    )
    (items / "dec.md").write_text(
        "---\nid: DEC-001\ntype: decision\n---\n\nSee REQ-050 for context.\n",
        encoding="utf-8",
    )
    project = _former_ids_build(tmp_path)
    html = project.items["DEC-001"].body_html
    assert 'class="ref ref-former"' in html
    assert "(formerly REQ-050)" in html


def test_former_ids_shaped_like_a_legacy_underscore_id_only_link_explicitly(tmp_path):
    """`BARE_REF_RE` requires a `-<digits>` suffix, so an underscore-style former
    id like the CAN_00 example in finding 12 can never bare-autolink -- must
    stay reachable via [[CAN_00]], and the gap must be visible, not silent."""
    (tmp_path / "refdes.yaml").write_text(FORMER_IDS_SCHEMA, encoding="utf-8")
    items = tmp_path / "items"
    items.mkdir()
    (items / "r.yaml").write_text(
        "defaults: { type: requirement }\n"
        "items:\n  - id: REQ-001\n    text: Renumbered.\n    former_ids: [CAN_00]\n",
        encoding="utf-8",
    )
    (items / "dec.md").write_text(
        "---\nid: DEC-001\ntype: decision\n---\n\n"
        "Bare mention CAN_00 stays plain text. Explicit [[CAN_00]] still resolves.\n",
        encoding="utf-8",
    )
    project = _former_ids_build(tmp_path)
    assert any(
        "'CAN_00' does not match the bare-reference shape" in d.message
        and "[[CAN_00]]" in d.message
        for d in project.warnings
    )
    html = project.items["DEC-001"].body_html
    assert "Bare mention CAN_00 stays plain text" in html
    assert html.count('class="ref ref-former"') == 1  # only the explicit one resolved


# ------------------------------------- orphaned ledger allocations (finding 10 Part 2, narrower)


def _allocate_and_reload(root):
    """Allocate REQ-001 for real (writes the ledger + the item file), then
    return a freshly re-parsed project reflecting that write -- the shape
    every test below needs before it can edit the item file out from under
    the ledger's own memory of it."""
    project = load_project(config_path=str(root / "refdes.yaml"))
    parse.load_items(project, require_ids=False)
    assignments = ids.allocate(project)
    assert assignments and assignments[0][1] == "REQ-001"
    return load_project(config_path=str(root / "refdes.yaml"))


def test_orphaned_allocations_empty_while_the_item_is_still_live(tmp_path):
    root = _former_ids_project(
        tmp_path, "defaults: { type: requirement }\nitems:\n  - text: First item.\n"
    )
    project = _allocate_and_reload(root)
    parse.load_items(project, require_ids=False)
    assert ids.orphaned_allocations(project) == []


def test_orphaned_allocations_flags_a_deleted_unexplained_id(tmp_path):
    root = _former_ids_project(
        tmp_path, "defaults: { type: requirement }\nitems:\n  - text: First item.\n"
    )
    _allocate_and_reload(root)
    (root / "items" / "r.yaml").write_text("items: []\n", encoding="utf-8")
    project = load_project(config_path=str(root / "refdes.yaml"))
    parse.load_items(project, require_ids=False)
    assert ids.orphaned_allocations(project) == ["REQ-001"]


def test_orphaned_allocations_excludes_ids_explained_by_former_ids(tmp_path):
    """A rename recorded properly -- the sanctioned path -- must never be
    reported as if something went unexplained."""
    root = _former_ids_project(
        tmp_path, "defaults: { type: requirement }\nitems:\n  - text: First item.\n"
    )
    _allocate_and_reload(root)
    (root / "items" / "r.yaml").write_text(
        "defaults: { type: requirement }\n"
        "items:\n  - id: REQ-002\n    text: Renamed.\n    former_ids: [REQ-001]\n",
        encoding="utf-8",
    )
    project = load_project(config_path=str(root / "refdes.yaml"))
    parse.load_items(project, require_ids=False)
    assert ids.orphaned_allocations(project) == []


def test_orphaned_allocations_cannot_see_a_same_id_reuse(tmp_path):
    """The documented limitation, encoded as a test rather than left as a
    claim in a docstring: once a different item is hand-typed with the
    exact former id, the entry re-explains itself and this function goes
    back to reporting nothing -- it is not a fix for finding 10's own
    repro, only for the narrower window before the id is retyped."""
    root = _former_ids_project(
        tmp_path, "defaults: { type: requirement }\nitems:\n  - text: First item.\n"
    )
    _allocate_and_reload(root)
    (root / "items" / "r.yaml").write_text(
        "defaults: { type: requirement }\n"
        "items:\n  - id: REQ-001\n    text: A different item, same reused id.\n",
        encoding="utf-8",
    )
    project = load_project(config_path=str(root / "refdes.yaml"))
    parse.load_items(project, require_ids=False)
    assert ids.orphaned_allocations(project) == []


def test_cli_audit_reports_orphaned_allocations(tmp_path, capsys):
    root = _former_ids_project(
        tmp_path, "defaults: { type: requirement }\nitems:\n  - text: First item.\n"
    )
    _allocate_and_reload(root)
    (root / "items" / "r.yaml").write_text("items: []\n", encoding="utf-8")
    assert cli_mod.main(["-c", str(root / "refdes.yaml"), "audit"]) == 0
    out = capsys.readouterr().out
    assert "Ledger entries with no live item and no former_ids: explaining them:" in out
    assert "REQ-001" in out


def test_cli_audit_orphaned_allocations_is_none_when_clean(tmp_path, capsys):
    root = _former_ids_project(
        tmp_path, "defaults: { type: requirement }\nitems:\n  - text: First item.\n"
    )
    _allocate_and_reload(root)
    assert cli_mod.main(["-c", str(root / "refdes.yaml"), "audit"]) == 0
    out = capsys.readouterr().out
    section = out.split("Ledger entries with no live item")[1].split("\n\n")[0]
    assert "(none)" in section


def test_cli_audit_lists_former_ids(tmp_path, capsys):
    (tmp_path / "refdes.yaml").write_text(FORMER_IDS_SCHEMA, encoding="utf-8")
    items = tmp_path / "items"
    items.mkdir()
    (items / "r.yaml").write_text(
        "defaults: { type: requirement }\n"
        "items:\n  - id: REQ-001\n    text: Renumbered.\n    former_ids: [REQ-050]\n",
        encoding="utf-8",
    )
    assert cli_mod.main(["-c", str(tmp_path / "refdes.yaml"), "audit"]) == 0
    out = capsys.readouterr().out
    assert "Former IDs:" in out
    assert "REQ-050" in out and "REQ-001" in out


def test_items_json_exports_former_ids(tmp_path):
    (tmp_path / "refdes.yaml").write_text(FORMER_IDS_SCHEMA, encoding="utf-8")
    items = tmp_path / "items"
    items.mkdir()
    (items / "r.yaml").write_text(
        "defaults: { type: requirement }\n"
        "items:\n  - id: REQ-001\n    text: Renumbered.\n    former_ids: [REQ-050]\n",
        encoding="utf-8",
    )
    project = _former_ids_build(tmp_path)
    payload = render.items_json(project)
    entry = next(i for i in payload["items"] if i["id"] == "REQ-001")
    assert entry["former_ids"] == ["REQ-050"]


# ---------------------------------------------------- former-ids propose command


def _propose_build(root):
    project = load_project(config_path=str(root / "refdes.yaml"))
    parse.load_items(project, require_ids=False)
    build_mod.build(project, seal_write=False, reseal=False)
    return project


def test_propose_errors_with_no_baseline_stamped(tmp_path):
    root = _former_ids_project(tmp_path, "defaults: { type: requirement }\nitems: []\n")
    project = _propose_build(root)
    with pytest.raises(former_ids.ProposeError, match="no baseline stamped yet"):
        former_ids.propose(project)


def test_propose_matches_a_renumbered_item_by_title_similarity(tmp_path):
    root = _former_ids_project(
        tmp_path,
        "defaults: { type: requirement }\n"
        "items:\n  - id: REQ-001\n"
        "    text: The bus shall recover from a bit error within one frame.\n",
    )
    project = _propose_build(root)
    lifecycle.stamp(project, kind="revision", name="rev-a")

    (root / "items" / "r.yaml").write_text(
        "defaults: { type: requirement }\n"
        "items:\n  - id: REQ-002\n"
        "    text: The bus shall recover from a bit error within one frame.\n",
        encoding="utf-8",
    )
    project2 = _propose_build(root)
    candidates = former_ids.propose(project2)
    assert len(candidates) == 1
    c = candidates[0]
    assert (c.old_id, c.new_id) == ("REQ-001", "REQ-002")
    assert c.confidence == 1.0


def test_propose_ignores_a_removed_id_already_resolved(tmp_path):
    """An old id another item already claims via former_ids: is done -- it
    must not show up again as a fresh candidate."""
    root = _former_ids_project(
        tmp_path,
        "defaults: { type: requirement }\n"
        "items:\n  - id: REQ-001\n    text: A requirement.\n",
    )
    project = _propose_build(root)
    lifecycle.stamp(project, kind="revision", name="rev-a")

    (root / "items" / "r.yaml").write_text(
        "defaults: { type: requirement }\n"
        "items:\n"
        "  - id: REQ-002\n    text: A requirement.\n    former_ids: [REQ-001]\n"
        "  - id: REQ-003\n    text: A different, unrelated requirement.\n",
        encoding="utf-8",
    )
    project2 = _propose_build(root)
    assert former_ids.propose(project2) == []


def test_propose_confirm_writes_former_ids_and_rejects_unknown_names(tmp_path):
    root = _former_ids_project(
        tmp_path,
        "defaults: { type: requirement }\n"
        "items:\n  - id: REQ-001\n    text: A migrated requirement.\n",
    )
    project = _propose_build(root)
    lifecycle.stamp(project, kind="revision", name="rev-a")

    (root / "items" / "r.yaml").write_text(
        "defaults: { type: requirement }\n"
        "items:\n  - id: REQ-002\n    text: A migrated requirement.\n",
        encoding="utf-8",
    )
    project2 = _propose_build(root)
    candidates = former_ids.propose(project2)

    with pytest.raises(former_ids.ProposeError, match="not a currently proposed candidate"):
        former_ids.confirm(project2, candidates, ["REQ-999"])

    confirmed = former_ids.confirm(project2, candidates, ["REQ-001"])
    assert [c.new_id for c in confirmed] == ["REQ-002"]
    assert project2.former_ids["REQ-001"] == "REQ-002"

    text = (root / "items" / "r.yaml").read_text(encoding="utf-8")
    assert "former_ids: [REQ-001]" in text

    # And it's now durable: reparsing the rewritten file resolves cleanly.
    project3 = _propose_build(root)
    assert not project3.errors
    assert project3.former_ids["REQ-001"] == "REQ-002"


def test_cli_former_ids_propose_shows_candidates_then_writes_on_confirm(tmp_path, capsys):
    root = _former_ids_project(
        tmp_path,
        "defaults: { type: requirement }\n"
        "items:\n  - id: REQ-001\n    text: A migrated requirement.\n",
    )
    project = _propose_build(root)
    lifecycle.stamp(project, kind="revision", name="rev-a")

    (root / "items" / "r.yaml").write_text(
        "defaults: { type: requirement }\n"
        "items:\n  - id: REQ-002\n    text: A migrated requirement.\n",
        encoding="utf-8",
    )

    status = cli_mod.main(["-c", str(root / "refdes.yaml"), "former-ids", "propose"])
    assert status == 0
    out = capsys.readouterr().out
    assert "REQ-001" in out and "REQ-002" in out
    assert "Nothing written" in out
    assert "former_ids: [REQ-001]" not in (root / "items" / "r.yaml").read_text(encoding="utf-8")

    status = cli_mod.main(
        ["-c", str(root / "refdes.yaml"), "former-ids", "propose", "--confirm", "REQ-001"]
    )
    assert status == 0
    out = capsys.readouterr().out
    assert "wrote former_ids: [REQ-001] to REQ-002" in out
    assert "former_ids: [REQ-001]" in (root / "items" / "r.yaml").read_text(encoding="utf-8")
