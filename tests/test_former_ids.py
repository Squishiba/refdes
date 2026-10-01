"""former_ids -- and: orphaned ledger allocations (finding 10 Part 2, narrower), former-ids propose command.

Split out of the original monolithic tests/test_refdes.py.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from conftest import write_project_config

from refdes import build as build_mod
from refdes import cli as cli_mod
from refdes import former_ids, ids, keys as keys_mod, lifecycle, parse, render
from refdes.schema import load_project

# ------------------------------------------------------------------ former_ids

FORMER_IDS_SCHEMA = (
    "site: { title: T, out: _site }\n"
    "types:\n"
    "  requirement: { prefix: REQ, fields: { text: { type: text } } }\n"
    "  decision: { prefix: DEC, fields: {}, body: {} }\n"
)


def _former_ids_project(tmp_path, items_yaml):
    write_project_config(tmp_path, FORMER_IDS_SCHEMA)
    items = tmp_path / "items"
    items.mkdir()
    (items / "r.yaml").write_text(items_yaml, encoding="utf-8")
    return tmp_path


def _former_ids_build(root):
    project = load_project(config_path=str(root / "refdes-project.yaml"))
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
    project = load_project(config_path=str(root / "refdes-project.yaml"))
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
    write_project_config(tmp_path, FORMER_IDS_SCHEMA)
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
    html = project.item_by_id("DEC-001").body_html
    assert 'class="ref ref-former"' in html
    assert 'href="req-001.html"' in html
    assert 'data-ref="REQ-001"' in html
    assert "(formerly REQ-050)" in html


def test_former_ids_resolve_bare_reference_when_it_fits_the_bare_pattern(tmp_path):
    write_project_config(tmp_path, FORMER_IDS_SCHEMA)
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
    html = project.item_by_id("DEC-001").body_html
    assert 'class="ref ref-former"' in html
    assert "(formerly REQ-050)" in html


def test_former_id_prose_link_text_is_the_current_id_not_the_old_one(tmp_path):
    """The visible text is the *current* id; the marker names the former one.

    docs/ids.md ("a reader following the old id needs to see it landed
    somewhere else") is the requirement. Rendering the reference's own text
    gave "REQ-050 (formerly REQ-050)" -- self-contradictory, and with the
    destination named nowhere on the page.
    """
    write_project_config(tmp_path, FORMER_IDS_SCHEMA)
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
    assert not project.errors
    html = project.item_by_id("DEC-001").body_html
    assert (
        '<a class="ref ref-former" href="req-001.html" data-ref="REQ-001">REQ-001</a>'
        '<span class="ref-former-marker" title="REQ-001 was formerly REQ-050">'
        "(formerly REQ-050)</span>"
    ) in html
    # ...and specifically not the self-contradictory rendering.
    assert ">REQ-050</a>" not in html
    assert "REQ-050 (formerly REQ-050)" not in html


def test_former_id_prose_link_keeps_an_explicit_label_as_its_text(tmp_path):
    """`[[old|label]]`: the label is the author's own words, so it stays the
    link text -- only the marker's former-id naming is added to it."""
    write_project_config(tmp_path, FORMER_IDS_SCHEMA)
    items = tmp_path / "items"
    items.mkdir()
    (items / "r.yaml").write_text(
        "defaults: { type: requirement }\n"
        "items:\n  - id: REQ-001\n    text: Renumbered.\n    former_ids: [REQ-050]\n",
        encoding="utf-8",
    )
    (items / "dec.md").write_text(
        "---\nid: DEC-001\ntype: decision\n---\n\nSee [[REQ-050|the rail spec]].\n",
        encoding="utf-8",
    )
    project = _former_ids_build(tmp_path)
    assert not project.errors
    html = project.item_by_id("DEC-001").body_html
    assert (
        '<a class="ref ref-former" href="req-001.html" data-ref="REQ-001">'
        "the rail spec</a>"
        '<span class="ref-former-marker" title="REQ-001 was formerly REQ-050">'
        "(formerly REQ-050)</span>"
    ) in html


def test_former_ids_shaped_like_a_legacy_underscore_id_only_link_explicitly(tmp_path):
    """`BARE_REF_RE` requires a `-<digits>` suffix, so an underscore-style former
    id like the CAN_00 example in finding 12 can never bare-autolink -- must
    stay reachable via [[CAN_00]], and the gap must be visible, not silent."""
    write_project_config(tmp_path, FORMER_IDS_SCHEMA)
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
    html = project.item_by_id("DEC-001").body_html
    assert "Bare mention CAN_00 stays plain text" in html
    assert html.count('class="ref ref-former"') == 1  # only the explicit one resolved


# ------------------------------------- orphaned ledger allocations (finding 10 Part 2, narrower)


def _allocate_and_reload(root):
    """Allocate REQ-001 for real (writes the ledger + the item file), then
    return a freshly re-parsed project reflecting that write -- the shape
    every test below needs before it can edit the item file out from under
    the ledger's own memory of it."""
    project = load_project(config_path=str(root / "refdes-project.yaml"))
    parse.load_items(project, require_ids=False)
    assignments = ids.allocate(project)
    assert assignments and assignments[0][1] == "REQ-001"
    return load_project(config_path=str(root / "refdes-project.yaml"))


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
    project = load_project(config_path=str(root / "refdes-project.yaml"))
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
    project = load_project(config_path=str(root / "refdes-project.yaml"))
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
    project = load_project(config_path=str(root / "refdes-project.yaml"))
    parse.load_items(project, require_ids=False)
    assert ids.orphaned_allocations(project) == []


def test_cli_audit_reports_orphaned_allocations(tmp_path, capsys):
    root = _former_ids_project(
        tmp_path, "defaults: { type: requirement }\nitems:\n  - text: First item.\n"
    )
    _allocate_and_reload(root)
    (root / "items" / "r.yaml").write_text("items: []\n", encoding="utf-8")
    assert cli_mod.main(["-c", str(root / "refdes-project.yaml"), "audit"]) == 0
    out = capsys.readouterr().out
    assert "Ledger entries with no live item and no former_ids: explaining them:" in out
    assert "REQ-001" in out


def test_cli_audit_orphaned_allocations_is_none_when_clean(tmp_path, capsys):
    root = _former_ids_project(
        tmp_path, "defaults: { type: requirement }\nitems:\n  - text: First item.\n"
    )
    _allocate_and_reload(root)
    assert cli_mod.main(["-c", str(root / "refdes-project.yaml"), "audit"]) == 0
    out = capsys.readouterr().out
    section = out.split("Ledger entries with no live item")[1].split("\n\n")[0]
    assert "(none)" in section


def test_cli_audit_lists_former_ids(tmp_path, capsys):
    write_project_config(tmp_path, FORMER_IDS_SCHEMA)
    items = tmp_path / "items"
    items.mkdir()
    (items / "r.yaml").write_text(
        "defaults: { type: requirement }\n"
        "items:\n  - id: REQ-001\n    text: Renumbered.\n    former_ids: [REQ-050]\n",
        encoding="utf-8",
    )
    assert cli_mod.main(["-c", str(tmp_path / "refdes-project.yaml"), "audit"]) == 0
    out = capsys.readouterr().out
    assert "Former IDs:" in out
    assert "REQ-050" in out and "REQ-001" in out


def test_items_json_exports_former_ids(tmp_path):
    write_project_config(tmp_path, FORMER_IDS_SCHEMA)
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
    project = load_project(config_path=str(root / "refdes-project.yaml"))
    parse.load_items(project, require_ids=False)
    build_mod.build(project, seal_write=False, reseal=False)
    return project


def test_propose_errors_with_no_baseline_stamped(tmp_path):
    root = _former_ids_project(tmp_path, "defaults: { type: requirement }\nitems: []\n")
    project = _propose_build(root)
    with pytest.raises(former_ids.ProposeError, match="no baseline stamped yet"):
        former_ids.propose(project)


def test_propose_reports_the_real_old_title_for_a_keyed_rename(tmp_path):
    """A baseline is keyed by *display* id and carries the surrogate in a
    `key:` field, so looking the entry up under the surrogate itself misses
    and every exact candidate used to print its old title as empty -- the one
    field that tells a human which item they are about to re-identify."""
    key = keys_mod.mint()
    root = _former_ids_project(
        tmp_path,
        "defaults: { type: requirement }\n"
        f"items:\n  - id: REQ-001\n    key: {key}\n    text: The bus shall recover.\n",
    )
    project = _propose_build(root)
    lifecycle.stamp(project, kind="revision", name="rev-a")

    (root / "items" / "r.yaml").write_text(
        "defaults: { type: requirement }\n"
        f"items:\n  - id: REQ-002\n    key: {key}\n    text: The bus shall recover.\n",
        encoding="utf-8",
    )
    project2 = _propose_build(root)
    candidates = former_ids.propose(project2)
    assert len(candidates) == 1
    c = candidates[0]
    assert (c.old_id, c.new_id) == ("REQ-001", "REQ-002")
    assert c.exact and c.confidence == 1.0
    assert c.old_title == "The bus shall recover."
    assert c.old_type == "requirement"


def test_cli_propose_prints_the_old_title_of_a_keyed_rename(tmp_path, capsys):
    """The empty title was visible in the command's own output, not just in
    the API -- which is where a reviewer would have noticed it."""
    key = keys_mod.mint()
    root = _former_ids_project(
        tmp_path,
        "defaults: { type: requirement }\n"
        f"items:\n  - id: REQ-001\n    key: {key}\n    text: The bus shall recover.\n",
    )
    project = _propose_build(root)
    lifecycle.stamp(project, kind="revision", name="rev-a")

    (root / "items" / "r.yaml").write_text(
        "defaults: { type: requirement }\n"
        f"items:\n  - id: REQ-002\n    key: {key}\n    text: The bus shall recover.\n",
        encoding="utf-8",
    )
    status = cli_mod.main(["-c", str(root / "refdes-project.yaml"), "former-ids", "propose"])
    assert status == 0
    out = capsys.readouterr().out
    assert "REQ-001 (requirement 'The bus shall recover.')" in out


def test_propose_reports_the_real_old_title_for_an_adopted_key_keyed_rename(tmp_path):
    """`refdes keys adopt` flips the map to key-keyed with the display id
    inside -- the shape the buggy lookup *did* handle. Both shapes have to
    keep working, so this pins the second one explicitly."""
    key = keys_mod.mint()
    root = _former_ids_project(
        tmp_path,
        "defaults: { type: requirement }\n"
        f"items:\n  - id: REQ-001\n    key: {key}\n    text: The bus shall recover.\n",
    )
    project = _propose_build(root)
    lifecycle.stamp(project, kind="revision", name="rev-a")
    assert cli_mod.main(["-c", str(root / "refdes-project.yaml"), "keys", "adopt"]) == 0

    (root / "items" / "r.yaml").write_text(
        "defaults: { type: requirement }\n"
        f"items:\n  - id: REQ-002\n    key: {key}\n    text: The bus shall recover.\n",
        encoding="utf-8",
    )
    project2 = _propose_build(root)
    candidates = former_ids.propose(project2)
    assert len(candidates) == 1
    assert candidates[0].old_title == "The bus shall recover."


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

    status = cli_mod.main(["-c", str(root / "refdes-project.yaml"), "former-ids", "propose"])
    assert status == 0
    out = capsys.readouterr().out
    assert "REQ-001" in out and "REQ-002" in out
    assert "Nothing written" in out
    assert "former_ids: [REQ-001]" not in (root / "items" / "r.yaml").read_text(encoding="utf-8")

    status = cli_mod.main(
        ["-c", str(root / "refdes-project.yaml"), "former-ids", "propose", "--confirm", "REQ-001"]
    )
    assert status == 0
    out = capsys.readouterr().out
    assert "wrote former_ids: [REQ-001] to REQ-002" in out
    assert "former_ids: [REQ-001]" in (root / "items" / "r.yaml").read_text(encoding="utf-8")


# ------------------------------- looking a retired id up (finding F3.2, scenario 3)
#
# Before this, a renamed item was findable by `refdes audit` and by the built
# items.json and by nothing else: `refdes ls REQ-PWR-001` answered "no items
# match" and the item's own page never named the id it used to have -- so
# "where did REQ-PWR-001 go?" had no cheap answer anywhere. See
# in-prog-logs/keys-identity-recovery.txt scenario 3 (F3.2).

LOOKUP_SCHEMA = (
    "site: { title: T, out: _site }\n"
    "types:\n"
    "  requirement: { prefix: REQ, fields: { text: { type: text } } }\n"
    "  decision: { prefix: DEC, fields: {}, body: {} }\n"
)


def _lookup_project(tmp_path, items_yaml="defaults: { type: requirement }\n"
                                          "items:\n"
                                          "  - id: REQ-001\n"
                                          "    text: Renumbered.\n"
                                          "    former_ids: [REQ-050]\n"
                                          "  - id: REQ-002\n"
                                          "    text: Untouched.\n"):
    return _former_ids_project_with(LOOKUP_SCHEMA, items_yaml, tmp_path)


def _former_ids_project_with(schema, items_yaml, tmp_path):
    write_project_config(tmp_path, schema)
    items = tmp_path / "items"
    items.mkdir()
    (items / "r.yaml").write_text(items_yaml, encoding="utf-8")
    return tmp_path


def test_ls_finds_an_item_by_a_retired_id_and_marks_it(tmp_path, capsys):
    root = _lookup_project(tmp_path)
    status = cli_mod.main(["-c", str(root / "refdes-project.yaml"), "ls", "REQ-050"])
    assert status == 0
    out = capsys.readouterr().out
    # The current id leads, and the retired one is named -- the listing has to
    # say *where the old id went*, not just that something matches.
    assert "REQ-001" in out
    assert "(formerly REQ-050)" in out
    assert "REQ-002" not in out
    assert "no items match" not in out


def test_ls_retired_id_match_uses_the_same_substring_and_case_rules(tmp_path, capsys):
    """The same query that finds a live id finds a retired one: a person
    typing `req-050` or half of it after reading it in a commit message gets
    the same answer, not a second spelling to remember."""
    root = _lookup_project(tmp_path)
    assert cli_mod.main(["-c", str(root / "refdes-project.yaml"), "ls", "req-050"]) == 0
    assert "REQ-001" in capsys.readouterr().out
    assert cli_mod.main(["-c", str(root / "refdes-project.yaml"), "ls", "q-05"]) == 0
    assert "REQ-001" in capsys.readouterr().out


def test_ls_listing_is_unchanged_for_a_query_that_names_no_former_id(tmp_path, capsys):
    """Existing matching keeps working exactly as it did, and the marker is
    not sprayed over every row: it appears only where the query met a former
    id."""
    root = _lookup_project(tmp_path)
    assert cli_mod.main(["-c", str(root / "refdes-project.yaml"), "ls", "REQ-001"]) == 0
    out = capsys.readouterr().out
    assert "(formerly" not in out
    assert cli_mod.main(["-c", str(root / "refdes-project.yaml"), "ls"]) == 0
    out = capsys.readouterr().out
    assert "(formerly" not in out
    assert "REQ-001" in out and "REQ-002" in out


def test_ls_reports_every_retired_id_the_item_carries(tmp_path, capsys):
    root = _lookup_project(
        tmp_path,
        "defaults: { type: requirement }\n"
        "items:\n"
        "  - id: REQ-001\n"
        "    text: Twice renumbered.\n"
        "    former_ids: [REQ-050, REQ-060]\n",
    )
    assert cli_mod.main(["-c", str(root / "refdes-project.yaml"), "ls", "REQ-0"]) == 0
    out = capsys.readouterr().out
    assert "(formerly REQ-050, REQ-060)" in out


def test_ls_a_reused_retired_id_resolves_to_the_live_item_that_holds_it_now(tmp_path, capsys):
    """A retired id reused by a new item is the live item's id, so the live
    item is what the listing answers with -- and the former holder is named
    under the table rather than listed as though the query had found it."""
    root = _lookup_project(
        tmp_path,
        "defaults: { type: requirement }\n"
        "items:\n"
        "  - id: REQ-001\n"
        "    text: Renumbered.\n"
        "    former_ids: [REQ-050]\n"
        "  - id: REQ-050\n"
        "    text: Minted the retired id back.\n",
    )
    status = cli_mod.main(["-c", str(root / "refdes-project.yaml"), "ls", "REQ-050"])
    out = capsys.readouterr().out
    assert status == 0
    assert "REQ-050" in out  # the live item, listed as itself...
    assert "Minted the retired id back." in out
    # ...the former holder named in the note, not as a hit, and the reason.
    assert "REQ-001" in out  # the note, which is where it appears
    note = [line for line in out.splitlines() if line.startswith("note:")]
    assert len(note) == 1
    assert "REQ-050 is a live item's id again" in note[0]
    assert "REQ-001" in note[0]
    # The former holder must not also read as a row the query matched.
    row = [line for line in out.splitlines() if line.startswith("REQ-001 ")]
    assert row == []


def test_ls_unknown_query_still_says_no_items_match(tmp_path, capsys):
    root = _lookup_project(tmp_path)
    assert cli_mod.main(["-c", str(root / "refdes-project.yaml"), "ls", "no-such-thing"]) == 0
    assert "no items match" in capsys.readouterr().out


def test_ls_help_says_the_query_reaches_former_ids(capsys):
    with pytest.raises(SystemExit) as excinfo:
        cli_mod.main(["ls", "--help"])
    assert excinfo.value.code == 0
    assert re.search(r"former_ids:", capsys.readouterr().out)


def test_the_item_page_names_its_own_former_ids(tmp_path):
    root = _lookup_project(tmp_path)
    project = _former_ids_build(root)
    out = Path(render.render_site(project))
    html = (out / "req-001.html").read_text(encoding="utf-8")
    assert "formerly known as" in html
    assert "REQ-050" in html
    # And an item that never renamed does not claim to have one.
    assert "formerly known as" not in (out / "req-002.html").read_text(encoding="utf-8")


def test_the_hover_preview_card_carries_the_item_former_ids(tmp_path):
    """The payload is what app.js builds the card from, so this is the card's
    data: `former_ids` present on a renamed item, absent (not empty) on one
    that has none, so a project that records no renames keeps byte-identical
    preview data."""
    root = _lookup_project(tmp_path)
    project = _former_ids_build(root)
    previews = render.preview_payload(project)
    assert previews["REQ-001"]["former_ids"] == ["REQ-050"]
    assert "former_ids" not in previews["REQ-002"]


def test_the_hover_card_renders_a_formerly_known_as_row():
    """No JS harness here (tests/test_vscode_extension.py says so for the
    extension), so this pins the card builder's own text: a former-id row is
    added to the card's field list, which is what styles it -- adding a
    stylesheet selector instead would fail tests/test_style_tokens.py."""
    app_js = (
        Path(__file__).resolve().parents[1]
        / "src"
        / "refdes"
        / "templates"
        / "assets"
        / "app.js"
    ).read_text(encoding="utf-8")
    assert "formerly known as" in app_js
    assert re.search(r"p\.former_ids", app_js)
    assert "rows.push(" in app_js
