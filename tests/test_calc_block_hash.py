"""Named calc blocks, Phase 4: hash pins (docs/design/named-calc-blocks.md
§6, §10). No implementation change is expected here -- these tests exist to
keep it that way. If one fails, that is a finding, not something to paper
over.

Sabotage-style: each "does not move" claim is paired with the mutation that
would falsify it -- putting the block name into a hash payload, into the
calc_refs contribution, or into calc_hash_for's captured text.
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
    """Edit an item file in place -- never rewrite it wholesale, or its
    minted key (front matter) would be lost and the item would become a new
    one (same discipline as tests/test_calc_cross_ref_hash.py)."""
    path = tmp_path / "items" / name
    text = path.read_text(encoding="utf-8")
    assert old in text, (old, text)
    path.write_text(text.replace(old, new), encoding="utf-8")


def test_hash_format_bumped_to_5_moves_nothing_here(tmp_path):
    """§6.1, re-pinned by the HASH_FORMAT 5 bump (editor-image-upload.md
    §15.6): naming still enters no payload as a new key -- the format-3-vs-4
    identity holds. And because this project has no images, the format-4-vs-5
    identity holds too: the image-bytes bump moves no image-free item, the
    same no-churn argument every earlier bump made. Sabotage: a `block`/
    `calc_blocks` key added to _hash_payload, or a format 5 that looks at
    anything but images, fails here."""
    assert build_mod.HASH_FORMAT == 5
    p = _build(tmp_path, {
        "a.md": _item("DEC-001", '```calc id="losses"\nV_in = 12 V\n```\n'),
        "b.md": _item("DEC-002", "prose only, no calc at all\n"),
    })
    assert not p.errors, p.errors
    for item in p.local_items:
        spec = p.types[item.type]
        five = build_mod.hash_payload_builder(p, 5)(item, spec)
        four = build_mod.hash_payload_builder(p, 4)(item, spec)
        three = build_mod.hash_payload_builder(p, 3)(item, spec)
        assert five == four == three
        assert item.content_hash == build_mod.hash_for_format(item, p, 4)


def test_naming_moves_owner_hash_only(tmp_path):
    """§6.1: the fence line is body text, so naming moves the OWNER's
    content_hash -- and nobody else's. Sabotage: a global churn (name folded
    into a shared seed) or a body hash that strips fences (owner unmoved)."""
    files = {
        "a.md": _item("DEC-001", "```calc\nV_in = 12 V\n```\n"),
        "b.md": _item("DEC-002", "```calc\nQ = 2 A\n```\n"),
    }
    h1 = _hashes(_build(tmp_path, files))
    _edit(tmp_path, "a.md", "```calc\nV_in", '```calc id="losses"\nV_in')
    p2 = _build(tmp_path, {})
    assert not p2.errors, p2.errors
    h2 = _hashes(p2)
    assert h2["DEC-001"] != h1["DEC-001"], "naming is an author edit to the owner's text"
    assert h2["DEC-002"] == h1["DEC-002"], "no other item's text changed"


def test_rename_block_leaves_dependents_alone(tmp_path):
    """§6.1: block names appear nowhere in _calc_reference_values, so a
    rename cannot move a dependent's hash or its calc_reference_snapshot.
    Sabotage: qualifying the reference payload with the block name, or
    hashing the owner's fence into the dependent."""
    owner = _item("DEC-001", '```calc id="losses"\nV_in = 12 V\n```\n')
    down = _item("DEC-002", "```calc\nV_copy = DEC-001.V_in\nP = V_copy * 2 A | W\n```\n")
    p1 = _build(tmp_path, {"a.md": owner, "b.md": down})
    assert not p1.errors, p1.errors
    h1 = _hashes(p1)
    snap1 = build_mod.calc_reference_snapshot(p1, p1.item_by_id("DEC-002"))

    _edit(tmp_path, "a.md", 'id="losses"', 'id="thermal"')
    p2 = _build(tmp_path, {})
    assert not p2.errors, p2.errors
    h2 = _hashes(p2)
    assert h2["DEC-001"] != h1["DEC-001"], "the owner's body changed"
    assert h2["DEC-002"] == h1["DEC-002"], "the dependent references no block"
    assert build_mod.calc_reference_snapshot(
        p2, p2.item_by_id("DEC-002")
    ) == snap1


def test_calc_hash_unaffected_by_fence(tmp_path):
    """§6.1: calc_hash_for hashes extract_blocks' captured group -- the
    block's contents -- and the fence line is outside it. Adding then
    renaming a fence name leaves calc_hash identical while content_hash
    moves each time. Sabotage: folding match.group(0) (the whole match,
    fence included) into calc_hash_for, the exact 'simplification' §6.1
    predicts."""
    files = {"a.md": _item("DEC-001", "```calc\nV_in = 12 V\n```\n")}
    p1 = _build(tmp_path, files)
    owner1 = p1.item_by_id("DEC-001")
    calc_hash_1 = build_mod.calc_hash_for(owner1)
    content_1 = owner1.content_hash
    assert calc_hash_1 is not None

    _edit(tmp_path, "a.md", "```calc\nV_in", '```calc id="losses"\nV_in')
    p2 = _build(tmp_path, {})
    owner2 = p2.item_by_id("DEC-001")
    assert build_mod.calc_hash_for(owner2) == calc_hash_1, "adding a name is not arithmetic"
    assert owner2.content_hash != content_1, "but it is an edit"

    _edit(tmp_path, "a.md", 'id="losses"', 'id="supply"')
    p3 = _build(tmp_path, {})
    owner3 = p3.item_by_id("DEC-001")
    assert build_mod.calc_hash_for(owner3) == calc_hash_1, "renaming is not arithmetic"
    assert owner3.content_hash not in (content_1, owner2.content_hash)
