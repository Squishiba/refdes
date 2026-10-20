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
              re.findall(r"```calc\n(.*?)```", body, re.DOTALL)]
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
    reports it as an error at the line. Sabotage: rewriting the malformed
    span's raw text moves the probe, so the probe is the span's text, not
    a constant standing in for it."""
    files = {"a.md": _item("DEC-001", "`x := 1 V`\n")}
    project = _build(tmp_path, files)
    assert any("stored result missing" in m for m in _errors(project))
    probe = build_mod.calc_hash_for(project.item_by_id("DEC-001"))
    assert probe is not None
    _edit(tmp_path, "a.md", "`x := 1 V`", "`x := 2 V`")
    project2 = _rebuild(tmp_path)
    assert build_mod.calc_hash_for(project2.item_by_id("DEC-001")) != probe


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


def test_span_reference_with_a_rhs_comment_expands(tmp_path):
    """Review chunk 2: the evaluator strips `#` comments before it matches
    a cross-reference, so a span whose reference carries a trailing
    comment is the same dependency edge -- it schedules after its target
    and expands to composite form like a comment-free span. Matching the
    raw RHS made it invisible to the scans: the span ran before its
    target and leaked an internal AttributeError instead of resolving."""
    import re

    files = {
        "a.md": "---\nid: DEC-001\ntype: decision\n---\n\n"
        "`v := DEC-002.V_in # note = 2 V`\n",
        "b.md": SPAN_REF["b.md"],
    }
    project = _build(tmp_path, files)
    assert not project.errors, _errors(project)
    text = (tmp_path / "items" / "a.md").read_text(encoding="utf-8")
    assert re.search(r"DEC-002@[A-Za-z0-9_-]+\.V_in", text), text


def test_span_source_with_a_rhs_comment_is_discovered(tmp_path):
    """Review chunk 2, the same parity for `source()`: the evaluator's
    discovery walk (`calc.source_calls_in_block`) strips a trailing `#`
    comment with the quote-aware `split_comment` before it matches the
    call, and `evaluate_block` strips it from the span's RHS before it
    evaluates -- a commented span is a live `source()` to both. `fetch`
    must pin the key it names: a span `fetch` does not see is a value
    the build demands and fetch never takes (the F12-6 dead end)."""
    import yaml

    from refdes import cli as cli_mod

    config = (
        "site: { title: T, out: _site }\n"
        "types:\n  decision:\n    prefix: DEC\n    fields:\n"
        "      citations: { type: citations, on_change: invalidate }\n"
    )
    files = {
        "a.md": "---\nid: DEC-001\ntype: decision\ncitations:\n"
        "  - path: analysis/budget.csv\n---\n\n"
        '`k := source("analysis/budget.csv", "k1") | V # note = 5 V`\n'
    }
    config_path = _setup(tmp_path, files, config)
    (tmp_path / "analysis").mkdir(exist_ok=True)
    (tmp_path / "analysis" / "budget.csv").write_text("key,value\nk1,5.0\n", encoding="utf-8")

    assert cli_mod.main(["-c", config_path, "fetch"]) == 0
    lock = yaml.safe_load(
        (tmp_path / ".refdes" / "citations.yaml").read_text(encoding="utf-8")
    )
    assert "k1" in lock["citations"]["analysis/budget.csv"]["values"], lock
    # and the commented span is a live calc: the build evaluates it clean.
    # (The `# note | V` shape -- comment BEFORE the unit -- is NOT the
    # parity shape: the evaluator's comment strip swallows the unit, so it
    # demands an explicit unit at build. The unit is part of the
    # expression grammar; the comment follows it.)
    project = load_project(config_path=config_path)
    parse.load_items(project)
    build_mod.build(project)
    assert not project.errors, _errors(project)


def test_a_comment_containing_a_pipe_keeps_the_span_a_reference(tmp_path):
    """Round-3 review (chunk 2): `parse_span` splits `| unit` BEFORE the
    trailing `#` comment, the evaluator strips the comment FIRST -- a
    comment containing a `|` lands the pipe split on the comment's pipe
    (the unit class is `[^|]+`) and hides the reference from the scans,
    reviving the F12-5 leak: with no edge the span's item runs first (the
    a.md file order) and the resolver resolves its reference against a
    target with no evaluated environment -- the internal
    `'Item' object has no attribute '_env'`. The scan helpers match in the
    evaluator's order, so the edge exists and the build is clean."""
    files = {
        "a.md": _item("DEC-002", "`v := DEC-001.V_in | V # a | b = 12 V`\n"),
        "z.md": _item("DEC-001", "```calc\nV_in = 12 V\n```\n"),
    }
    project = _build(tmp_path, files)
    assert not project.errors, _errors(project)


def test_a_comment_containing_a_pipe_keeps_the_span_a_source_call(tmp_path):
    """Round-3 review (chunk 2), the same shape for `source()`: the
    evaluator strips the comment (quote-aware) before splitting the unit,
    so `` source(...) | V # a | b `` is a live call to it and `fetch`
    must pin its key -- the split-order hole made the key invisible to
    discovery while the build demanded the pin (the F12-6 dead end, this
    shape)."""
    import yaml

    from refdes import cli as cli_mod

    config = (
        "site: { title: T, out: _site }\n"
        "types:\n  decision:\n    prefix: DEC\n    fields:\n"
        "      citations: { type: citations, on_change: invalidate }\n"
    )
    files = {
        "a.md": "---\nid: DEC-001\ntype: decision\ncitations:\n"
        "  - path: analysis/budget.csv\n---\n\n"
        '`k := source("analysis/budget.csv", "k1") | V # a | b = 5 V`\n'
    }
    config_path = _setup(tmp_path, files, config)
    (tmp_path / "analysis").mkdir(exist_ok=True)
    (tmp_path / "analysis" / "budget.csv").write_text("key,value\nk1,5.0\n", encoding="utf-8")

    assert cli_mod.main(["-c", config_path, "fetch"]) == 0
    lock = yaml.safe_load(
        (tmp_path / ".refdes" / "citations.yaml").read_text(encoding="utf-8")
    )
    assert "k1" in lock["citations"]["analysis/budget.csv"]["values"], lock
    project = load_project(config_path=config_path)
    parse.load_items(project)
    build_mod.build(project)
    assert not project.errors, _errors(project)


# ------------------------------------------------- 3. scan geometry (review)


FRONT_MATTER_FENCE = (
    "---\nid: DEC-001\ntype: decision\nsummary: |\n  ```\n---\n\n"
    "`v := DEC-002.V_in = 2 V`\n"
)


def test_unclosed_fence_in_front_matter_does_not_hide_the_span(tmp_path):
    """Review chunk 3: the file scan was bounded at the front-matter fence
    line, so front matter ending in an unclosed fence marker (valid YAML
    in a block scalar) left the span scan's fence state open across the
    body -- every span of the item silently stopped being a reference:
    no expansion, no report, forever. The scan is bounded to the body."""
    import re

    files = {"a.md": FRONT_MATTER_FENCE, "b.md": SPAN_REF["b.md"]}
    project = _build(tmp_path, files)
    assert not project.errors, _errors(project)
    text = (tmp_path / "items" / "a.md").read_text(encoding="utf-8")
    assert re.search(r"DEC-002@[A-Za-z0-9_-]+\.V_in", text), text


def test_span_in_front_matter_is_not_rewritten(tmp_path):
    """Review chunk 3, the other side of the bound: a triggered span inside
    front matter is no span consumer's business -- body, hash and
    citations all scan the body -- so the on-disk rewrite must leave it
    alone; rewriting it while the in-memory pass rewrites only
    `item.body` splits file and memory apart. The item's body carries a
    reference to the same target, which is what puts the item in the
    plan and starts the scan."""
    import re

    files = {
        "a.md": '---\nid: DEC-001\ntype: decision\nsummary: "see `x := DEC-002.V_in = 1 V`"\n---\n\n'
        "body: `v := DEC-002.V_in = 1 V`\n",
        "b.md": "---\nid: DEC-002\ntype: decision\n---\n\n```calc\nV_in = 1 V\n```\n",
    }
    project = _build(tmp_path, files)
    assert not project.errors, _errors(project)
    text = (tmp_path / "items" / "a.md").read_text(encoding="utf-8")
    assert re.search(r"body: `v := DEC-002@[A-Za-z0-9_-]+\.V_in = 1 V`", text), text
    assert 'summary: "see `x := DEC-002.V_in = 1 V`"' in text, text


# ------------------------------ 4. slice 2 evidence (c)/(d)/(e) in a project


CROSS_SPAN = {
    "up.md": _item("DEC-001", "```calc\nV_in = 12 V\n```\n"),
    "down.md": _item("DEC-002", "`v := DEC-001.V_in = 12 V`\n"),
}


def test_editing_a_referenced_value_moves_the_span_item(tmp_path):
    """Evidence (c): the value a span reads is a real dependency -- editing
    the upstream number moves the span item's content hash, and the
    scheduler ordered the build so the span resolved against the new value
    (no stale `= 12 V` verdict change, which the probe reports)."""
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
    contributes every distinct target to the baseline snapshot's
    `calc_refs` (the snapshot set is deduplicated -- the repeated
    `DEC-001.V_in` names one target once), and the probe covers all three
    spans: the probe is span-ordered per occurrence, so dropping the
    duplicated third span moves it even though the snapshot set is
    unchanged."""
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
    import re

    path = tmp_path / "items" / "mid.md"
    text = path.read_text(encoding="utf-8")
    trimmed = re.sub(r" and `c := DEC-001@[^.]+\.V_in = 12 V`", "", text)
    assert trimmed != text, text
    path.write_text(trimmed, encoding="utf-8")
    project2 = _rebuild(tmp_path)
    entry2 = lifecycle._items_map(project2)["DEC-003"]
    assert entry2["calc_refs"] == entry["calc_refs"]  # snapshot set: deduped
    assert entry2["calc_hash"] != entry["calc_hash"]  # probe: all three spans


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


# ------------------------- 5. the HIGH fix: format-5 reconstruction of an
# expanded span (round-2 review)


APPEND_CONFIG = (
    "site: { title: T, out: _site }\n"
    "types:\n  decision: { prefix: DEC, append_only: true, fields: {} }\n"
)

# The old-code seal of the CROSS_SPAN fixture, recorded by running main
# (d620ab5, HASH_FORMAT 5) over it on 2026-10-20. The test cannot
# regenerate it -- that is the point: it is the value a real project has
# stored in its seal file, and the format-5 reconstruction must reproduce
# it from the *expanded* text the slice-2 rewriter leaves on disk.
SEALED_UNDER_FORMAT5 = {
    "DEC-001": "e44d58abd0c521ca",
    "DEC-002": "c564abc555f17ffa",
}


def test_expanded_span_keeps_verifying_an_old_format5_seal(tmp_path):
    """HIGH (round-2 review): slice 2 rewrites a span's target to the
    composite form on disk, which moves the item's text -- so verifying a
    seal recorded at format 5 must reconstruct the format-5 body with the
    expanded span target stripped back to its display half. Before the
    fix, a project sealed on main failed its very next build with
    'DEC-002 is append-only and has been modified since it was sealed'
    purely because the rewriter touched it. Format 6 moves the hash
    (that is the designed migration); format-5 reconstruction must not."""
    _setup(tmp_path, CROSS_SPAN, APPEND_CONFIG)
    (tmp_path / ".refdes").mkdir(exist_ok=True)
    (tmp_path / ".refdes" / "log-seal.yaml").write_text(
        "sealed:\n"
        f"  DEC-001: {SEALED_UNDER_FORMAT5['DEC-001']}\n"
        f"  DEC-002: {SEALED_UNDER_FORMAT5['DEC-002']}\n",
        encoding="utf-8",
    )
    project = _rebuild(tmp_path)
    assert not project.errors, _errors(project)
    assert project.seal_violations == []
    spanned = project.item_by_id("DEC-002")
    # the designed migration: the current (6) hash moved, the 5-reconstruction
    # is the stored seal.
    assert spanned.content_hash != SEALED_UNDER_FORMAT5["DEC-002"]
    assert build_mod.hash_for_format(spanned, project, 5) == SEALED_UNDER_FORMAT5["DEC-002"]
    fence = project.item_by_id("DEC-001")
    assert fence.content_hash == SEALED_UNDER_FORMAT5["DEC-001"]


def test_sealed_span_item_round_trips_then_detects_a_real_edit(tmp_path):
    """Sealing a span item at the current format: the first writable build
    seals it, a clean rebuild verifies, and editing the span's arithmetic
    trips the append-only lock -- the seal check reads the *expanded* text
    at format 6 (the strip applies to legacy reconstruction only)."""
    from refdes import seal

    project = _build(tmp_path, CROSS_SPAN, APPEND_CONFIG)
    build_mod.build(project, seal_write=True)
    sealed = seal.load_seals(project)
    assert sealed["DEC-002"] == project.item_by_id("DEC-002").content_hash

    project2 = _rebuild(tmp_path)
    assert not project2.errors, _errors(project2)
    assert project2.seal_violations == []

    _edit(tmp_path, "down.md", "V_in = 12 V", "V_in = 12 V + 0")
    project3 = _rebuild(tmp_path)
    assert "DEC-002" in project3.seal_violations
    assert any("modified since it was sealed" in m for m in _errors(project3))


# --------------------- 6. the round-2 review's two rewrite-scan fixes


def test_span_name_matching_the_target_prefix_is_not_eaten(tmp_path):
    """Round-2 review collision: with a one-letter type prefix, a span
    whose *name* starts with the reference's target (`v21 := v2.V_in`
    under prefix `v`) -- a `content.replace(target, new, 1)` rewrite hits
    the name first and corrupts the span into a composite-named calc. The
    rewriter splices the target at its recorded range, so name and target
    each stay their own text, and the expansion re-builds clean."""
    import re

    config = "site: { title: T, out: _site }\n" \
        "types:\n  volt: { prefix: v, fields: {} }\n"
    files = {
        "a.md": "---\nid: v2\ntype: volt\n---\n\n```calc\nV_in = 12 V\n```\n",
        "b.md": "---\nid: v21\ntype: volt\n---\n\n`v21 := v2.V_in = 12 V`\n",
    }
    _build(tmp_path, files, config)
    text = (tmp_path / "items" / "b.md").read_text(encoding="utf-8")
    assert re.search(r"`v21 := v2@[A-Za-z0-9_-]+\.V_in = 12 V`", text), text
    project = _rebuild(tmp_path)
    assert not project.errors, _errors(project)


def test_yaml_list_file_span_targets_stay_bare_on_disk(tmp_path):
    """Round-2 review exclusion: the rewriter's geometry is markdown
    (front-matter delimiters, calc fences, line offsets), so for an item
    loaded from a YAML list file -- `Item.body_line is None`, and a line
    rewrite of `body:` corrupts the YAML text -- the plan skips its
    span-only targets: the span stays bare on disk, a fenced reference
    (whose geometry *is* the item's own lines) still expands, and the
    dependency edge exists in the in-memory graph, so the build resolves
    clean and a `--no-write` report matches what a writable build leaves."""
    write_project_config(tmp_path, "site: { title: T, out: _site }\n")
    (tmp_path / "refdes-schema.yaml").write_text(
        "types:\n  decision: { prefix: DEC, fields: {} }\n", encoding="utf-8"
    )
    items = tmp_path / "items"
    items.mkdir(exist_ok=True)
    (items / "a.md").write_text(_item("DEC-001", "```calc\nV_in = 12 V\n```\n"), encoding="utf-8")
    yaml_text = (
        "items:\n"
        "  - id: DEC-002\n"
        "    type: decision\n"
        "    body: |\n"
        "      Prose with `v := DEC-001.V_in = 12 V` span.\n"
        "\n"
        "      ```calc\n"
        "      w = DEC-001.V_in\n"
        "      ```\n"
    )
    (items / "b.yaml").write_text(yaml_text, encoding="utf-8")
    project = _rebuild(tmp_path)
    assert not project.errors, _errors(project)
    text = (items / "b.yaml").read_text(encoding="utf-8")
    assert "v := DEC-001.V_in = 12 V" in text, text  # span bare, geometry-safe
    import re

    assert re.search(r"w = DEC-001@[A-Za-z0-9_-]+\.V_in", text), text  # fence expands
    project2 = _rebuild(tmp_path)
    assert not project2.errors, _errors(project2)


def test_yaml_list_file_span_hash_is_stable_across_runs(tmp_path):
    """Round-3 review (chunk 3): the file path excludes list-file spans
    from expansion, but the in-memory pass shared the same replacement map
    and had no body-position guard -- with a fence and a span naming the
    SAME target, the first writable load rewrote the span in memory only.
    That run's `calc_hash` (which hashes `item.body` raw) and its rendered
    page carried the composite target; every later build of the same bytes
    sees the bare span, so a baseline stamped by the expansion run records
    a probe no later run reproduces, and the stale-arithmetic signal
    (fires only on equality) is silently dead for the item. Two consecutive
    writable loads of unchanged bytes must agree on the probe."""
    write_project_config(tmp_path, "site: { title: T, out: _site }\n")
    (tmp_path / "refdes-schema.yaml").write_text(
        "types:\n  decision: { prefix: DEC, fields: {} }\n", encoding="utf-8"
    )
    items = tmp_path / "items"
    items.mkdir(exist_ok=True)
    (items / "a.md").write_text(_item("DEC-001", "```calc\nV_in = 12 V\n```\n"), encoding="utf-8")
    (items / "b.yaml").write_text(
        "items:\n"
        "  - id: DEC-002\n"
        "    type: decision\n"
        "    body: |\n"
        "      Prose with `v := DEC-001.V_in = 12 V` span.\n"
        "\n"
        "      ```calc\n"
        "      w = DEC-001.V_in\n"
        "      ```\n",
        encoding="utf-8",
    )
    first = _rebuild(tmp_path)
    assert not first.errors, _errors(first)
    probe1 = lifecycle._items_map(first)["DEC-002"]["calc_hash"]
    html1 = first.item_by_id("DEC-002").body_html
    second = _rebuild(tmp_path)
    assert not second.errors, _errors(second)
    probe2 = lifecycle._items_map(second)["DEC-002"]["calc_hash"]
    assert probe1 == probe2, (probe1, probe2)
    assert first.item_by_id("DEC-002").body_html == html1


def test_span_and_fence_rewrites_on_one_line_both_land(tmp_path):
    """Round-3 review (chunk 3): a line that is fence-grammar (a pipe-unit
    assignment) AND carries a triggered span, with both of its targets
    expandable -- the span edits were applied to `lines[i]`, then the
    assignment pass recomputed from the stale `raw` and wrote the line from
    that, silently discarding the span rewrite while `applied` (and so
    `plan.rewrites`) already counted it: a reported rewrite that never
    happened. The assignment pass anchors on the span-edited line, so both
    rewrites land on the first writable run."""
    import re

    files = {
        "a.md": _item("DEC-001", "```calc\nV_in = 12 V\n```\n"),
        "b.md": _item("DEC-002", "```calc\nV_in = 5 V\n```\n"),
        "c.md": _item(
            "DEC-003",
            "```calc\nw = DEC-002.V_in\n```\n\n"
            "gain = DEC-002.V_in | V `s := DEC-001.V_in = 12 V`\n",
        ),
    }
    project = _build(tmp_path, files)
    assert not project.errors, _errors(project)
    text = (tmp_path / "items" / "c.md").read_text(encoding="utf-8")
    assert re.search(r"gain = DEC-002@[A-Za-z0-9_-]+\.V_in", text), text
    assert re.search(r"`s := DEC-001@[A-Za-z0-9_-]+\.V_in = 12 V`", text), text


def test_crossed_composite_span_target_in_a_list_file_still_warns(tmp_path):
    """Round-4 review (chunk 3): the list-file skip of span-only targets
    ran BEFORE `_planned_target`, which is where the crossed-reference
    refusal-and-warn (docs/design/keys.md §3 case 2) is emitted. A stale
    composite span target in a YAML-list-file item (`DEC-001@<key-of-
    DEC-002>`, DEC-001 a different live item) lost the warning entirely
    while the identical reference in a fence line of the same file warned:
    the build resolves by key, so the page shows DEC-002 while the source
    says DEC-001, and the warning is the only signal of the bad merge. The
    WRITE exclusion stays; the lint runs."""
    project = _build(
        tmp_path,
        {
            "a.md": _item("DEC-001", "```calc\nV_in = 12 V\n```\n"),
            "b.md": _item("DEC-002", "```calc\nV_in = 5 V\n```\n"),
        },
    )
    assert not project.errors, _errors(project)
    key2 = project.item_by_id("DEC-002").key
    assert key2
    text = (
        "items:\n"
        "  - id: DEC-003\n"
        "    type: decision\n"
        "    body: |\n"
        f"      Prose `v := DEC-001@{key2}.V_in = 12 V` span.\n"
    )
    (tmp_path / "items" / "c.yaml").write_text(text, encoding="utf-8")
    after = _rebuild(tmp_path)
    warns = [
        d.message
        for d in after.warnings
        if "different live item" in d.message
    ]
    assert len(warns) == 1, [d.message for d in after.warnings + after.errors]
    assert f"'DEC-001@{key2}'" in warns[0]
    after_text = (tmp_path / "items" / "c.yaml").read_text(encoding="utf-8")
    assert f"`v := DEC-001@{key2}.V_in = 12 V`" in after_text


# ------------------------- 7. an author-written composite span target under
# format 5 (round-6 review): format-5 code accepted and hashed
# `DISPLAY@key.V_in` in a span verbatim, so the reconstruction that strips
# every composite target must not be the ONLY legacy reading a comparison
# accepts -- an item nobody edited would look edited. The fixture's key
# front matter makes the recorded hashes below stable.

AUTHORED_FIXTURE = {
    "a.md": (
        "---\nkey: w4fq61wx8v7\nid: DEC-001\ntype: decision\n---\n\n"
        "```calc\nV_in = 12 V\n```\n"
    ),
    "e.md": (
        "---\nkey: rff8vmeh0av\nid: DEC-005\ntype: decision\n---\n\n"
        "The divider tracks DEC-001: `Vout := DEC-001@w4fq61wx8v7.V_in = 12 V`.\n"
    ),
}
# Recorded by running main (c3073c6, HASH_FORMAT 5) over these exact bytes
# (revision + release, 2026-10-20). The test cannot regenerate them, and
# the stripped format-5 reconstruction does not reproduce DEC-005's --
# carrying this item forward means honoring the hash the code of the day
# recorded for text it accepted.
AUTHORED_SEALED_UNDER_FORMAT5 = {
    "DEC-001": "e44d58abd0c521ca",
    "DEC-005": "a4cfb87eab2994b6",
}
# The stripped reading of the same body: the format-5 hash the span target
# would have if it had been authored bare (pinned against the bare twin in
# test_composite_span_variants_are_narrow).
STRIPPED_UNDER_FORMAT5 = "833d7cb975540ba9"


def _write_baseline(tmp_path, entries: dict):
    import yaml

    baselines = tmp_path / ".refdes" / "baselines"
    baselines.mkdir(parents=True, exist_ok=True)
    data = {
        "kind": "revision",
        "name": "rev-a",
        "stamped_at": "2026-10-20T10:36:20Z",
        "stamped_by": "test",
        "refdes_version": "0.5.0",
        "items": entries,
    }
    (baselines / "rev-a.yaml").write_text(yaml.safe_dump(data), encoding="utf-8")


def test_authored_composite_span_target_keeps_verifying_an_old_format5_seal(tmp_path):
    """MEDIUM (round-6 review, reproduced against archived main): an item
    with an author-written composite span target, sealed by main's own
    code at format 5, is UNCHANGED -- but head reconstructed its format-5
    body with the composite stripped and reported the first build after
    the seal as `DEC-005 is append-only and has been modified since it
    was sealed`. The comparison side now accepts both legitimate format-5
    readings; the seal file below is byte-for-byte what main wrote."""
    _setup(tmp_path, AUTHORED_FIXTURE, APPEND_CONFIG)
    (tmp_path / ".refdes").mkdir(exist_ok=True)
    (tmp_path / ".refdes" / "log-seal.yaml").write_text(
        "sealed:\n"
        f"  DEC-001: {AUTHORED_SEALED_UNDER_FORMAT5['DEC-001']}\n"
        f"  DEC-005: {AUTHORED_SEALED_UNDER_FORMAT5['DEC-005']}\n",
        encoding="utf-8",
    )
    project = _rebuild(tmp_path)
    assert not project.errors, _errors(project)
    assert project.seal_violations == []
    spanned = project.item_by_id("DEC-005")
    # the recorded hash is the as-written reading, not the stripped one:
    assert build_mod.hash_for_format(spanned, project, 5) == STRIPPED_UNDER_FORMAT5
    assert AUTHORED_SEALED_UNDER_FORMAT5["DEC-005"] in build_mod.hash_for_format_variants(
        spanned, project, 5
    )


def test_authored_composite_span_baseline_entry_carries_forward(tmp_path):
    """The same item under the baseline migration: a format-5 entry holding
    main's recorded hash must be `carried`, not `uncomparable` -- the
    keys.md §5(c) promise for an item whose content never moved."""
    _setup(tmp_path, AUTHORED_FIXTURE, APPEND_CONFIG)
    _write_baseline(
        tmp_path,
        {
            "DEC-001": {
                "hash": AUTHORED_SEALED_UNDER_FORMAT5["DEC-001"],
                "type": "decision",
                "title": "upstream",
                "hash_format": 5,
                "key": "w4fq61wx8v7",
            },
            "DEC-005": {
                "hash": AUTHORED_SEALED_UNDER_FORMAT5["DEC-005"],
                "type": "decision",
                "title": "span",
                "hash_format": 5,
                "key": "rff8vmeh0av",
            },
        },
    )
    project = _rebuild(tmp_path)
    baseline = lifecycle.load_baseline(project, "rev-a")
    report = lifecycle.migrate_hash_format(project, baseline, write=False)
    assert report.uncomparable == []
    assert sorted(report.carried) == ["DEC-001", "DEC-005"]


def test_edited_authored_composite_span_is_still_detected(tmp_path):
    """The safety property of the widened comparison: a real edit to the
    span moves BOTH format-5 readings, so a pre-edit seal still fails and
    a pre-edit baseline entry is still `uncomparable`. The fix accepts two
    readings of one text, not two texts."""
    from refdes import seal

    _setup(tmp_path, AUTHORED_FIXTURE, APPEND_CONFIG)
    _write_baseline(
        tmp_path,
        {
            "DEC-005": {
                "hash": AUTHORED_SEALED_UNDER_FORMAT5["DEC-005"],
                "type": "decision",
                "title": "span",
                "hash_format": 5,
                "key": "rff8vmeh0av",
            },
        },
    )
    (tmp_path / ".refdes" / "log-seal.yaml").write_text(
        f"sealed:\n  DEC-005: {AUTHORED_SEALED_UNDER_FORMAT5['DEC-005']}\n",
        encoding="utf-8",
    )
    _edit(tmp_path, "e.md", "= 12 V`", "= 13 V`")
    project = _rebuild(tmp_path)
    assert "DEC-005" in project.seal_violations
    assert any("modified since it was sealed" in m for m in _errors(project))
    baseline = lifecycle.load_baseline(project, "rev-a")
    report = lifecycle.migrate_hash_format(project, baseline, write=False)
    assert report.carried == []
    assert report.uncomparable == ["DEC-005"]
    assert seal.load_seals(project)["DEC-005"] == AUTHORED_SEALED_UNDER_FORMAT5["DEC-005"]


def test_composite_span_variants_are_narrow(tmp_path):
    """The variant set is exactly the two format-5 readings for a composite
    span target (as-written + stripped), a single hash for a bare one, the
    single current hash at the current format, and None outside the
    formats this build understands. Nothing else moves."""
    project = _build(tmp_path, AUTHORED_FIXTURE, APPEND_CONFIG)
    spanned = project.item_by_id("DEC-005")
    assert build_mod.hash_for_format_variants(spanned, project, 5) == {
        STRIPPED_UNDER_FORMAT5,
        AUTHORED_SEALED_UNDER_FORMAT5["DEC-005"],
    }
    assert build_mod.hash_for_format_variants(
        spanned, project, build_mod.HASH_FORMAT
    ) == {spanned.content_hash}
    assert build_mod.hash_for_format_variants(spanned, project, 0) is None
    assert build_mod.hash_for_format_variants(spanned, project, 99) is None
    bare_files = dict(AUTHORED_FIXTURE)
    bare_files["e.md"] = AUTHORED_FIXTURE["e.md"].replace("@w4fq61wx8v7", "")
    bare = _build(tmp_path, bare_files, APPEND_CONFIG)
    bare_spanned = bare.item_by_id("DEC-005")
    # a bare-authored item lands on the same two readings once the plan
    # expands it in memory -- its stripped reconstruction is the control
    # the seal/migration tests above pin against.
    assert build_mod.hash_for_format(bare_spanned, bare, 5) == STRIPPED_UNDER_FORMAT5
    assert build_mod.hash_for_format_variants(bare_spanned, bare, 5) == {
        STRIPPED_UNDER_FORMAT5,
        AUTHORED_SEALED_UNDER_FORMAT5["DEC-005"],
    }
    # a span with no cross-item target: stripping is a no-op, one reading.
    plain = _build(
        tmp_path, {"a.md": AUTHORED_FIXTURE["a.md"]}, APPEND_CONFIG
    )
    assert build_mod.hash_for_format_variants(
        plain.item_by_id("DEC-001"), plain, 5
    ) == {AUTHORED_SEALED_UNDER_FORMAT5["DEC-001"]}


def _bare_fixture(fixture: dict) -> dict:
    bare = dict(fixture)
    bare["e.md"] = fixture["e.md"].replace("@w4fq61wx8v7", "")
    return bare


def test_key_half_edit_of_expanded_span_target_is_never_carried(tmp_path):
    """MEDIUM (round-7 review): the stripped format-5 reading is the
    pre-expansion bare text -- so a KEY-HALF-only edit of an
    expansion-written composite (`DEC-001@w4fq61wx8v7` ->
    `DEC-001@<DEC-002's key>`, the display half untouched) strips right
    back to the bare body a format-5 baseline/seal recorded, and the edit
    was silently carried forward as "content demonstrably unchanged".
    The stripped reading must only be accepted for composites faithful to
    what the expansion writes -- key half == the key of the item the
    display half names. The legitimate expansion itself keeps comparing
    clean."""
    from refdes import seal

    bare_files = _bare_fixture(AUTHORED_FIXTURE)
    bare_files["c.md"] = (
        "---\nid: DEC-002\ntype: decision\n---\n\n```calc\nV_in = 7 V\n```\n"
    )
    project = _build(tmp_path, bare_files, APPEND_CONFIG)
    assert not project.errors, _errors(project)
    other_key = project.item_by_id("DEC-002").key
    assert other_key and other_key != "w4fq61wx8v7"
    # the build expanded the span target to the faithful composite
    assert "DEC-001@w4fq61wx8v7.V_in" in (tmp_path / "items" / "e.md").read_text(
        encoding="utf-8"
    )
    # a format-5 baseline/seal recorded by the pre-expansion bare bytes
    # (the bare twin's format-5 hash is the stripped constant).
    _write_baseline(
        tmp_path,
        {
            "DEC-005": {
                "hash": STRIPPED_UNDER_FORMAT5,
                "type": "decision",
                "title": "span",
                "hash_format": 5,
                "key": "rff8vmeh0av",
            },
        },
    )
    (tmp_path / ".refdes" / "log-seal.yaml").write_text(
        f"sealed:\n  DEC-005: {STRIPPED_UNDER_FORMAT5}\n", encoding="utf-8"
    )
    # legitimate expansion: an untouched item compares clean under both.
    project = _rebuild(tmp_path)
    assert project.seal_violations == []
    baseline = lifecycle.load_baseline(project, "rev-a")
    report = lifecycle.migrate_hash_format(project, baseline, write=False)
    assert report.carried == ["DEC-005"]
    assert report.uncomparable == []
    # key-half-only edit: the span now points at DEC-002's key.
    _edit(tmp_path, "e.md", "DEC-001@w4fq61wx8v7.V_in", f"DEC-001@{other_key}.V_in")
    project = _rebuild(tmp_path)
    assert "DEC-005" in project.seal_violations
    baseline = lifecycle.load_baseline(project, "rev-a")
    report = lifecycle.migrate_hash_format(project, baseline, write=False)
    assert report.carried == []
    assert report.uncomparable == ["DEC-005"]
    assert seal.load_seals(project)["DEC-005"] == STRIPPED_UNDER_FORMAT5


def test_malformed_stored_hashes_never_raise(tmp_path):
    """LOW (round-7 review): the variant comparison replaced `stored ==
    hash` with set membership, which raises TypeError on an unhashable
    stored hash (a YAML list in a corrupted record). The comparison must
    keep the pre-variant posture: a non-string stored hash is a plain
    non-match -- migration reports it uncomparable, the seal check
    reports the ordinary violation, neither crashes."""
    from refdes import seal

    project = _build(tmp_path, _bare_fixture(AUTHORED_FIXTURE), APPEND_CONFIG)
    assert not project.errors, _errors(project)
    _write_baseline(
        tmp_path,
        {
            "DEC-005": {
                "hash": ["not", "a", "string"],
                "type": "decision",
                "title": "span",
                "hash_format": 5,
                "key": "rff8vmeh0av",
            },
        },
    )
    (tmp_path / ".refdes" / "log-seal.yaml").write_text(
        "sealed:\n  DEC-005: [not, a, string]\n", encoding="utf-8"
    )
    project = _rebuild(tmp_path)
    assert "DEC-005" in project.seal_violations
    baseline = lifecycle.load_baseline(project, "rev-a")
    report = lifecycle.migrate_hash_format(project, baseline, write=False)
    assert report.carried == []
    assert report.uncomparable == ["DEC-005"]
    assert seal.load_seals(project)["DEC-005"] == "['not', 'a', 'string']"
    plan = keys.plan_surrogate_storage(project, baseline.items, {})
    assert plan.baseline_uncomparable == ["DEC-005"]
