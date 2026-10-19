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


# ------------------------------------------- 2. cross-item span references


SPAN_REF = {
    "a.md": "---\nid: DEC-001\ntype: decision\n---\n\n"
    "`v := DEC-002.V_in = 2 V`\n",
    "b.md": "---\nid: DEC-002\ntype: decision\n---\n\n"
    "```calc\nV_in = 2 V\n```\n",
}


def test_span_reference_expands_to_composite_form(tmp_path):
    """The target half of an inline span's cross-item reference gets the
    same `DISPLAY-ID@key` expansion as a fence line (docs/design/keys.md
    rule, applied to spans by slice 2), and the expanded text re-builds
    clean and idempotently."""
    import re

    _build(tmp_path, SPAN_REF)
    text = (tmp_path / "items" / "a.md").read_text(encoding="utf-8")
    assert re.search(r"`v := DEC-002@[A-Za-z0-9_-]+\.V_in = 2 V`", text), text
    project = _rebuild(tmp_path)
    assert not project.errors
    text2 = (tmp_path / "items" / "a.md").read_text(encoding="utf-8")
    assert text2 == text, "expansion is idempotent"
    assert "2 V" in project.item_by_id("DEC-001").body_html


def test_span_reference_cycle_is_reported(tmp_path):
    """A span reference participates in the cycle graph: a span reading an
    item whose fence reads the span's item is an error naming the cycle,
    not a hang and not a silently-unresolvable reference."""
    files = {
        "a.md": "---\nid: DEC-001\ntype: decision\n---\n\n"
        "`v := DEC-002.w = 1 V`\n",
        "b.md": "---\nid: DEC-002\ntype: decision\n---\n\n"
        "```calc\nw = DEC-001.v\n```\n",
    }
    project = _build(tmp_path, files)
    cycles = [m for m in _errors(project) if "calc reference cycle" in m]
    assert len(cycles) == 1, _errors(project)
    assert "DEC-001 -> DEC-002 -> DEC-001" in cycles[0]


# ------------------------------ 5. slice 2 evidence (c)/(d)/(e) in a project


CROSS_SPAN = {
    "up.md": _item("DEC-001", "```calc\nV_in = 12 V\n```\n"),
    "down.md": _item("DEC-002", "`v := DEC-001.V_in = 12 V`\n"),
}


def test_editing_a_referenced_value_moves_the_span_item(tmp_path):
    """Evidence (c): the value a span reads is a real dependency -- editing
    the upstream number moves the span item's content hash, and the
    scheduler ordered the build so the span resolved against the new value
    (no stale `= 24 V` verdict change, which the probe reports)."""
    project = _build(tmp_path, CROSS_SPAN)
    assert not project.errors, _errors(project)
    before = _hashes(project)
    _edit(tmp_path, "up.md", "V_in = 12 V", "V_in = 13 V")
    after = _build(tmp_path, {})
    assert _hashes(after)["DEC-002"] != before["DEC-002"]
    assert _hashes(after)["DEC-001"] != before["DEC-001"]
    verdict = [
        d.message
        for d in after.warnings + after.errors
        if "stored result says" in d.message
    ]
    assert len(verdict) == 1, _errors(after)


def test_result_only_edit_keeps_the_span_probe(tmp_path):
    """Evidence (c), the other half: editing only the written-out result in
    the prose moves the content hash (body invalidates) but not the
    arithmetic probe -- the probe hashes `name := rhs | unit`, never the
    author's printed answer."""
    project = _build(tmp_path, CROSS_SPAN)
    probe = build_mod.calc_hash_for(project.item_by_id("DEC-002"))
    body_hash = _hashes(project)["DEC-002"]
    _edit(tmp_path, "down.md", "= 12 V", "= 11 V")
    after = _build(tmp_path, {})
    assert _hashes(after)["DEC-002"] != body_hash
    assert build_mod.calc_hash_for(after.item_by_id("DEC-002")) == probe


def test_span_source_edit_moves_the_item(tmp_path):
    """Evidence (d): a span's `source()` input is pinned by `fetch` and its
    locked value enters the hash -- moving the number in the source file
    (with `--update`) moves the span item's content hash."""
    from refdes import cli as cli_mod

    config = (
        "site: { title: T, out: _site }\n"
        "types:\n  decision:\n    prefix: DEC\n    fields:\n"
        "      citations: { type: citations, on_change: invalidate }\n"
    )
    files = {
        "a.md": "---\nid: DEC-001\ntype: decision\ncitations:\n"
        "  - path: analysis/budget.csv\n---\n\n"
        '`k := source("analysis/budget.csv", "k1") | V = 5 V`\n'
    }
    config_path = _setup(tmp_path, files, config)
    (tmp_path / "analysis").mkdir(exist_ok=True)
    csv = tmp_path / "analysis" / "budget.csv"
    csv.write_text("key,value\nk1,5.0\n", encoding="utf-8")

    def build():
        project = load_project(config_path=config_path)
        parse.load_items(project)
        build_mod.build(project)
        return project

    assert cli_mod.main(["-c", config_path, "fetch"]) == 0
    project = build()
    assert not project.errors, _errors(project)
    before = _hashes(project)

    csv.write_text("key,value\nk1,6.0\n", encoding="utf-8")
    assert cli_mod.main(["-c", config_path, "fetch", "--update"]) == 0
    after = build()
    assert _hashes(after)["DEC-001"] != before["DEC-001"]


def test_span_missing_target_is_a_clean_error(tmp_path):
    """Evidence (e): a span naming a target that does not exist gets the
    standard cross-item error text, not a crash and not a silent skip."""
    project = _build(
        tmp_path,
        {"a.md": _item("DEC-001", "`v := GHOST-1.V_in = 1 V`\n")},
    )
    hits = [m for m in _errors(project) if "GHOST-1" in m]
    assert len(hits) == 1, _errors(project)
    assert "does not exist" in hits[0]


def test_several_spans_one_item_all_enter_the_snapshot(tmp_path):
    """Evidence (e): an item with three spans referencing two upstreams
    puts all three refs in the baseline snapshot in source order, and the
    probe covers all three."""
    files = {
        "up1.md": _item("DEC-001", "```calc\nV_in = 12 V\n```\n"),
        "up2.md": _item("DEC-002", "```calc\nI_in = 2 A\n```\n"),
        "mid.md": _item(
            "DEC-003",
            "`a := DEC-001.V_in = 12 V` and "
            "`b := DEC-002.I_in = 2 A` and "
            "`c := DEC-001.V_in = 12 V`\n",
        ),
    }
    project = _build(tmp_path, files)
    assert not project.errors, _errors(project)
    entry = lifecycle._items_map(project)["DEC-003"]
    refs = sorted(r.split(".")[1] for r in entry["calc_refs"])
    assert refs == ["I_in", "V_in"], entry["calc_refs"]
    assert entry["calc_hash"] == build_mod.calc_hash_for(
        project.item_by_id("DEC-003")
    )


def test_format5_reconstruction_excludes_span_inputs(tmp_path):
    """The carry-forward rule (docs/design/keys.md §5(c)): rebuilding an
    item's hash *as format 5* -- what existing seals and baselines were
    recorded under -- must exclude everything slice 2 added, so a format-5
    record migrates verbatim. A no-span item is byte-identical at 5 and 6;
    a span-referencing item moves at 6 and its 5-reconstruction is a
    different, stable value the seal check compares against."""
    project = _build(tmp_path, CROSS_SPAN)
    fence = project.item_by_id("DEC-001")
    spanned = project.item_by_id("DEC-002")
    assert build_mod.hash_for_format(fence, project, 5) == fence.content_hash
    assert build_mod.hash_for_format(fence, project, 6) == fence.content_hash
    assert build_mod.hash_for_format(spanned, project, 6) == spanned.content_hash
    assert build_mod.hash_for_format(spanned, project, 5) != spanned.content_hash
