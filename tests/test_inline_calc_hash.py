"""Inline calc spans enter calc_hash, the dependency scans and the content
hash (docs/design/inline-calc.md section 3, slice 2).

Sabotage-style, like tests/test_calc_cross_ref_hash.py: every claim is
paired with the mutation that ought to falsify it. The section-3 contract:

- calc_hash_for covers each span's name, RHS and unit assertion in source
  order, excluding the stored result -- a result-only edit leaves the probe
  fixed, an arithmetic edit moves it, and an inline-only item has a probe;
- a cross-item reference in a span is a dependency edge: the scheduler
  orders the target first, a moved upstream value moves the span item's
  content hash and the baseline diff names it, and the composite-key refresh
  expands span targets like fence targets;
- a source() as a whole span RHS is discovered by `refdes fetch` and its
  locked value enters the content hash, same rules as a fence line;
- HASH_FORMAT 6: an item without inline spans keeps its old content hash
  byte-for-byte (golden constants recorded by running main's code), a
  baseline/seal recorded at format <=5 keeps verifying, and only items
  whose spans have cross-item/source() inputs gain a new input.
"""

from __future__ import annotations

from conftest import write_project_config

from refdes import build as build_mod
from refdes import keys, lifecycle, links, parse
from refdes.schema import load_project

BASIC_CONFIG = (
    "site: { title: T, out: _site }\n"
    "types:\n  decision: { prefix: DEC, fields: {} }\n"
)


def _item(item_id: str, body: str) -> str:
    return f"---\nid: {item_id}\ntype: decision\n---\n\n{body}"


def _setup(tmp_path, files: dict[str, str], config=BASIC_CONFIG) -> str:
    write_project_config(tmp_path, config)
    items = tmp_path / "items"
    items.mkdir(exist_ok=True)
    for name, text in files.items():
        (items / name).write_text(text, encoding="utf-8")
    return str(tmp_path / "refdes-project.yaml")


def _build(tmp_path, files: dict[str, str], config=BASIC_CONFIG, write: bool = True):
    config_path = _setup(tmp_path, files, config) if files else _existing(tmp_path)
    project = load_project(config_path=config_path)
    parse.load_items(project)
    if keys.mint_missing(project, write=write):
        project.items = {}
        project.items_by_id = {}
        project.pending = []
        parse.load_items(project)
    links.expand_missing_calc_refs(project, write=write)
    build_mod.build(project)
    return project


def _existing(tmp_path):
    return str(tmp_path / "refdes-project.yaml")


def _rebuild(tmp_path, write: bool = True):
    return _build(tmp_path, {}, write=write)


def _edit(tmp_path, name: str, old: str, new: str) -> None:
    path = tmp_path / "items" / name
    text = path.read_text(encoding="utf-8")
    assert old in text, (old, text)
    path.write_text(text.replace(old, new), encoding="utf-8")


def _hashes(project):
    return {i.id: i.content_hash for i in project.local_items}


def _errors(project):
    return [d.message for d in project.errors]


# ------------------------------------------------- 1. calc_hash covers spans


def test_inline_only_item_has_a_calc_hash(tmp_path):
    project = _build(tmp_path, {"a.md": _item("DEC-001", "`Vout := 2 V * 2 = 4 V`\n")})
    assert not project.errors
    assert build_mod.calc_hash_for(project.item_by_id("DEC-001")) is not None


def test_result_only_edit_leaves_calc_hash_fixed(tmp_path):
    project = _build(tmp_path, {"a.md": _item("DEC-001", "`Vout := 2 V * 2 = 4 V`\n")})
    probe = build_mod.calc_hash_for(project.item_by_id("DEC-001"))
    _edit(tmp_path, "a.md", "= 4 V`", "= 4.00 V`")
    project2 = _rebuild(tmp_path)
    assert build_mod.calc_hash_for(project2.item_by_id("DEC-001")) == probe, (
        "the stored result is not arithmetic; the probe must stay fixed"
    )
    # The result edit is a real source edit: the content hash moves (body).
    assert project2.item_by_id("DEC-001").content_hash != (
        project.item_by_id("DEC-001").content_hash
    )


def test_arithmetic_edits_move_calc_hash(tmp_path):
    body = "`Vout := 2 V * 2 = 4 V`\n"
    project = _build(tmp_path, {"a.md": _item("DEC-001", body)})
    probe = build_mod.calc_hash_for(project.item_by_id("DEC-001"))
    for old, new in (
        ("2 V * 2", "2 V * 3"),  # the RHS
        ("Vout :=", "Vout2 :="),  # the name
        ("= 4 V`", "| V = 4 V`"),  # the unit assertion
    ):
        _edit(tmp_path, "a.md", old, new)
        moved = build_mod.calc_hash_for(_rebuild(tmp_path).item_by_id("DEC-001"))
        assert moved != probe, f"changing {old!r} is an arithmetic change"
        _edit(tmp_path, "a.md", new, old)  # restore for the next mutation
    assert build_mod.calc_hash_for(_rebuild(tmp_path).item_by_id("DEC-001")) == probe


def test_block_only_calc_hash_is_the_block_only_hash(tmp_path):
    """An item with fences and no spans hashes exactly as the blocks-only
    probe computed it, so no existing baseline's calc_hash churns."""
    body = "```calc\nV = 2 V\nP = V * 2 A | W\n```\n"
    project = _build(tmp_path, {"a.md": _item("DEC-001", body)})
    import hashlib
    import json
    import re

    blocks = [re.sub(r"\s+", " ", b).strip() for b in
              re.findall(r"```calc\n(.*?)```", body, re.S)]
    expected = hashlib.sha256(
        json.dumps({"calc_blocks": blocks}, sort_keys=True).encode()
    ).hexdigest()[:16]
    assert build_mod.calc_hash_for(project.item_by_id("DEC-001")) == expected


def test_calc_hash_orders_spans_and_fences_by_source(tmp_path):
    """The probe is positional: the same multiset of arithmetic in the two
    source orders hashes differently."""
    text_c = "```calc\nx = 1 V\n```\n\n`z := x + 1 V = 2 V`\n"
    text_d = "`z := x + 1 V = 2 V`\n\n```calc\nx = 1 V\n```\n"
    p1 = _build(tmp_path, {"a.md": _item("DEC-001", text_c)})
    h1 = build_mod.calc_hash_for(p1.item_by_id("DEC-001"))
    p2 = _build(tmp_path, {"a.md": _item("DEC-001", text_d)})
    h2 = build_mod.calc_hash_for(p2.item_by_id("DEC-001"))
    assert h1 != h2, "source order is part of the probe"


def test_malformed_span_has_a_probe_at_all(tmp_path):
    """A triggered span with no arithmetic to name still gets a probe (its
    raw text) -- the span is arithmetic the author declared, and the build
    reports it as an error at the line."""
    project = _build(tmp_path, {"a.md": _item("DEC-001", "`x := 1 V`\n")})
    assert any("stored result missing" in m for m in _errors(project))
    assert build_mod.calc_hash_for(project.item_by_id("DEC-001")) is not None


def test_stale_arithmetic_signal_silent_for_baseline_without_probe(tmp_path):
    """An old baseline stamped before spans entered the probe has no
    calc_hash field for an inline-only item -- the verdict-change signal
    must stay silent for it (docs/design/inline-calc.md section 3)."""
    config = (
        "site: { title: T, out: _site }\n"
        "types:\n  decision:\n    prefix: DEC\n"
        "    fields:\n"
        "      status: { type: enum, choices: [accepted, rejected],"
        " on_change: invalidate }\n"
    )
    _setup(tmp_path, {"a.md": _item("DEC-001", "`Vout := 2 V * 2 = 4 V`\n")}, config)
    project = load_project(config_path=str(tmp_path / "refdes-project.yaml"))
    parse.load_items(project)
    build_mod.build(project)
    lifecycle.stamp(project, kind="revision", name="rev-a")
    baseline = lifecycle.load_baseline(project, "rev-a")
    (entry,) = baseline.items.values()
    assert "calc_hash" in entry, "the new stamp records the span probe"
    del entry["calc_hash"]  # the pre-slice-2 baseline shape
    _edit(tmp_path, "a.md", "type: decision", "type: decision\nstatus: accepted")
    project2 = load_project(config_path=str(tmp_path / "refdes-project.yaml"))
    parse.load_items(project2)
    build_mod.build(project2)
    diff = lifecycle.diff_against(project2, baseline, write=False)
    assert "DEC-001" in diff.changed  # the status moved
    assert diff.stale_arithmetic == [], (
        "a baseline without the probe must be silent, never guess"
    )


def test_stale_arithmetic_signal_works_for_span_probe(tmp_path):
    """A baseline stamped under slice 2 uses the span probe like the fence
    probe: verdict moved with the span arithmetic fixed is the signal."""
    config = (
        "site: { title: T, out: _site }\n"
        "types:\n  decision:\n    prefix: DEC\n"
        "    fields:\n"
        "      status: { type: enum, choices: [accepted, rejected],"
        " on_change: invalidate }\n"
    )
    _setup(tmp_path, {"a.md": _item("DEC-001", "`Vout := 2 V * 2 = 4 V`\n")}, config)
    project = load_project(config_path=str(tmp_path / "refdes-project.yaml"))
    parse.load_items(project)
    build_mod.build(project)
    lifecycle.stamp(project, kind="revision", name="rev-a")
    baseline = lifecycle.load_baseline(project, "rev-a")
    _edit(tmp_path, "a.md", "type: decision", "type: decision\nstatus: accepted")
    project2 = load_project(config_path=str(tmp_path / "refdes-project.yaml"))
    parse.load_items(project2)
    build_mod.build(project2)
    diff = lifecycle.diff_against(project2, baseline, write=False)
    assert diff.stale_arithmetic == ["DEC-001"]
