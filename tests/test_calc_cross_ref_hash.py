"""Cross-item calc references enter the content hash (finding 35, chunk 2).

Sabotage-style: each test breaks one thing and asserts the hash reacts (or,
for the rename and no-reference cases, provably does not). A quiet mistake in
hashing looks like success, so every positive claim is paired with the
mutation that ought to falsify it.
"""

from __future__ import annotations

from conftest import write_project_config

from refdes import build as build_mod
from refdes import keys, links, parse
from refdes.schema import load_project

CONFIG = (
    "site: { title: T, out: _site }\n"
    "types:\n  decision: { prefix: DEC, fields: {} }\n"
)


def _item(item_id: str, body: str) -> str:
    return f"---\nid: {item_id}\ntype: decision\n---\n\n{body}"


def _build(tmp_path, files: dict[str, str], write: bool = True):
    write_project_config(tmp_path, CONFIG)
    items = tmp_path / "items"
    items.mkdir(exist_ok=True)
    for name, text in files.items():
        (items / name).write_text(text, encoding="utf-8")
    project = load_project(config_path=str(tmp_path / "refdes-project.yaml"))
    parse.load_items(project)
    if keys.mint_missing(project, write=write):
        project.items = {}
        project.items_by_id = {}
        project.pending = []
        parse.load_items(project)
    links.expand_missing_calc_refs(project, write=write)
    build_mod.build(project)
    return project


def _hashes(project):
    return {i.id: i.content_hash for i in project.local_items}


def _edit(tmp_path, name: str, old: str, new: str) -> None:
    """Edit an item file in place -- never rewrite it wholesale, or its minted
    key (front matter) would be lost and the item would become a new one."""
    path = tmp_path / "items" / name
    text = path.read_text(encoding="utf-8")
    assert old in text, (old, text)
    path.write_text(text.replace(old, new), encoding="utf-8")


UP = "```calc\nV_in = {v}\n```\n"
DOWN = "```calc\nV_in = DEC-001.V_in\nP = V_in * 2 A | W\n```\n"


def test_upstream_value_change_changes_dependent_hash(tmp_path):
    p1 = _build(tmp_path, {
        "a.md": _item("DEC-001", UP.format(v="12 V ± 5%")),
        "b.md": _item("DEC-002", DOWN),
    })
    assert not p1.errors
    h1 = _hashes(p1)
    _edit(tmp_path, "a.md", "12 V ± 5%", "11.4 V ± 5%")
    h2 = _hashes(_build(tmp_path, {}))
    assert h2["DEC-002"] != h1["DEC-002"], "dependent must show as changed"
    assert h2["DEC-001"] != h1["DEC-001"]


def test_upstream_tolerance_change_changes_dependent_hash(tmp_path):
    p1 = _build(tmp_path, {
        "a.md": _item("DEC-001", UP.format(v="12 V ± 5%")),
        "b.md": _item("DEC-002", DOWN),
    })
    h1 = _hashes(p1)
    _edit(tmp_path, "a.md", "12 V ± 5%", "12 V ± 10%")
    h2 = _hashes(_build(tmp_path, {}))
    assert h2["DEC-002"] != h1["DEC-002"]


def test_upstream_change_below_display_rounding_still_registers(tmp_path):
    p1 = _build(tmp_path, {
        "a.md": _item("DEC-001", UP.format(v="12.00001 V")),
        "b.md": _item("DEC-002", DOWN),
    })
    h1 = _hashes(p1)
    shown = p1.item_by_id("DEC-002").calc_values["V_in"]
    _edit(tmp_path, "a.md", "12.00001 V", "12.00002 V")
    p2 = _build(tmp_path, {})
    assert p2.item_by_id("DEC-002").calc_values["V_in"] == shown
    assert _hashes(p2)["DEC-002"] != h1["DEC-002"]


def test_unrelated_upstream_edit_does_not_change_dependent_hash(tmp_path):
    """Only a *referenced* value that moved counts: editing another name in
    the target, or its prose, leaves the dependent alone."""
    files = {
        "a.md": _item("DEC-001", "prose one\n\n```calc\nV_in = 12 V\nI_x = 3 A\n```\n"),
        "b.md": _item("DEC-002", DOWN),
    }
    h1 = _hashes(_build(tmp_path, files))
    _edit(tmp_path, "a.md", "prose one", "prose two")
    _edit(tmp_path, "a.md", "I_x = 3 A", "I_x = 9 A")
    h2 = _hashes(_build(tmp_path, {}))
    assert h2["DEC-001"] != h1["DEC-001"]
    assert h2["DEC-002"] == h1["DEC-002"]


def test_transitive_value_move_reaches_the_far_dependent(tmp_path):
    p1 = _build(tmp_path, {
        "a.md": _item("DEC-001", UP.format(v="12 V")),
        "b.md": _item("DEC-002", "```calc\nV_mid = DEC-001.V_in\n```\n"),
        "c.md": _item("DEC-003", "```calc\nV_far = DEC-002.V_mid\n```\n"),
    })
    assert not p1.errors
    h1 = _hashes(p1)
    _edit(tmp_path, "a.md", "12 V", "11 V")
    h2 = _hashes(_build(tmp_path, {}))
    assert h2["DEC-002"] != h1["DEC-002"]
    assert h2["DEC-003"] != h1["DEC-003"]


def test_display_id_rename_does_not_churn_dependent_hash(tmp_path):
    p1 = _build(tmp_path, {
        "a.md": _item("DEC-001", UP.format(v="12 V")),
        "b.md": _item("DEC-002", DOWN),
    })
    h1 = _hashes(p1)
    key = p1.item_by_id("DEC-001").key
    _edit(tmp_path, "a.md", "id: DEC-001", "id: DEC-777")
    p2 = _build(tmp_path, {})
    assert not p2.errors, p2.errors
    assert p2.item_by_id("DEC-777").key == key
    # The composite on disk was refreshed to the new display id...
    assert "DEC-777@" in (tmp_path / "items" / "b.md").read_text(encoding="utf-8")
    # ...and nothing about either hash moved.
    h2 = _hashes(p2)
    assert h2["DEC-002"] == h1["DEC-002"]
    assert h2["DEC-777"] == h1["DEC-001"]


def test_bare_to_composite_expansion_does_not_churn(tmp_path):
    # Mint keys first (no reference yet), then add the bare reference.
    _build(tmp_path, {
        "a.md": _item("DEC-001", UP.format(v="12 V")),
        "b.md": _item("DEC-002", "```calc\nQ = 1 A\n```\n"),
    })
    _edit(tmp_path, "b.md", "Q = 1 A", "V_in = DEC-001.V_in\nP = V_in * 2 A | W")
    bare = _hashes(_build(tmp_path, {}, write=False))
    assert "@" not in (tmp_path / "items" / "b.md").read_text(encoding="utf-8")
    expanded = _hashes(_build(tmp_path, {}, write=True))
    assert "DEC-001@" in (tmp_path / "items" / "b.md").read_text(encoding="utf-8")
    assert expanded["DEC-002"] == bare["DEC-002"]


def test_renamed_upstream_name_is_a_loud_error_not_a_stale_hash(tmp_path):
    _build(tmp_path, {
        "a.md": _item("DEC-001", UP.format(v="12 V")),
        "b.md": _item("DEC-002", DOWN),
    })
    _edit(tmp_path, "a.md", "V_in = 12 V", "V_supply = 12 V")
    p2 = _build(tmp_path, {})
    errs = [d for d in p2.errors if d.item_id == "DEC-002"]
    assert errs and "does not define 'V_in'" in errs[0].message
    assert errs[0].line is not None


def test_own_reference_line_edit_changes_hash(tmp_path):
    files = {
        "a.md": _item("DEC-001", "```calc\nV_in = 12 V\nV_b = 5 V\n```\n"),
        "b.md": _item("DEC-002", DOWN),
    }
    h1 = _hashes(_build(tmp_path, files))
    _edit(tmp_path, "b.md", ".V_in\nP", ".V_b\nP")
    assert _hashes(_build(tmp_path, {}))["DEC-002"] != h1["DEC-002"]


def test_no_reference_payload_is_identical_to_format_3(tmp_path):
    """The no-churn proof: for every item with no cross-item reference, the
    format-4 payload IS the format-3 payload, so no existing hash moves."""
    p = _build(tmp_path, {
        "a.md": _item("DEC-001", UP.format(v="12 V")),
        "b.md": _item("DEC-002", "prose only\n"),
        "c.md": _item("DEC-003", DOWN),
    })
    for item in p.local_items:
        spec = p.types[item.type]
        four = build_mod.hash_payload_builder(p, 4)(item, spec)
        three = build_mod.hash_payload_builder(p, 3)(item, spec)
        if item.id == "DEC-003":
            assert four != three and "calc_refs" in four
        else:
            assert four == three
            assert item.content_hash == build_mod.hash_for_format(item, p, 3)


def test_format_3_baseline_carries_forward_for_unchanged_items(tmp_path):
    """A baseline stamped under format 3 still verifies: unchanged items
    (with or without references) are carried to format 4, not flagged."""
    from refdes import lifecycle

    p = _build(tmp_path, {
        "a.md": _item("DEC-001", UP.format(v="12 V")),
        "b.md": _item("DEC-002", DOWN),
    })
    items = lifecycle._items_map(p)
    for item in p.local_items:
        items[item.id]["hash"] = build_mod.hash_for_format(item, p, 3)
        items[item.id]["hash_format"] = 3
    baseline = lifecycle.Baseline(
        name="b3", kind="baseline", stamped_at="t", stamped_by="x",
        refdes_version="0", items={k: dict(v) for k, v in items.items()},
    )
    diff = lifecycle.diff_against(p, baseline, write=False)
    assert diff.changed == []
    assert diff.uncomparable == []
