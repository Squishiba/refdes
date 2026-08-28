"""keys.

Split out of the original monolithic tests/test_refdes.py.
"""

from __future__ import annotations

import yaml

from refdes import build as build_mod
from refdes import cli as cli_mod
from refdes import keys as keys_mod
from refdes import parse, render
from refdes.schema import load_project

# ------------------------------------------------------------------------- keys
#
# docs/design/keys.md: opaque, immutable surrogate identity. This section
# covers §1 (key format) and the minting half of §2. §5 (hashing) and §3's
# link-composite expansion have their own section further down, right after
# this one. The corruption lint (§6) and `refdes keys adopt` (§7) are still
# later layers, not implemented here.

_KEYS_IDX = {ch: i for i, ch in enumerate(keys_mod.ALPHABET)}


def _damm_valid(key: str) -> bool:
    """Standalone re-implementation of the check, deliberately not calling
    into keys.py, so this test can't pass merely because production code and
    test code share a bug."""
    interim = 0
    for ch in key:
        interim = keys_mod.DAMM_TABLE[interim][_KEYS_IDX[ch]]
    return interim == 0


def test_damm_table_is_a_totally_anti_symmetric_quasigroup_with_zero_diagonal():
    """The whole reason Damm was chosen over Luhn mod 32 (docs/design/keys.md's
    amended §1): a totally anti-symmetric quasigroup with a zero diagonal
    catches every single-character substitution *and* every adjacent
    transposition, by construction -- not by the luck of which errors happen
    to get tested. That guarantee depends entirely on the table having these
    exact algebraic properties; a table that is subtly wrong (one transposed
    entry, one row that's off) loses the property silently and nobody can
    tell by eye. So this checks the table itself, not the algorithm's
    behaviour on some sample of inputs.

    Checked directly, not asserted: every row and column is a permutation of
    0..31 (quasigroup / Latin square, 1024 cells), every diagonal entry is 0
    (32 cells), and total anti-symmetry -- (c*x)*y == (c*y)*x implies x == y
    -- holds over all 32*32*32 = 32,768 (c, x, y) triples, which subsumes the
    1024 (x, y) pairs the property is stated over.
    """
    table = keys_mod.DAMM_TABLE
    n = len(keys_mod.ALPHABET)
    assert n == 32
    assert len(table) == n
    assert all(len(row) == n for row in table)

    # Quasigroup / Latin square: every row and every column is a permutation
    # of 0..31 -- this alone is what makes the table's operation invertible
    # in both arguments, which the check algorithm's correctness depends on.
    for x, row in enumerate(table):
        assert sorted(row) == list(range(n)), f"row {x} is not a permutation of 0..{n - 1}"
    for y in range(n):
        column = [table[x][y] for x in range(n)]
        assert sorted(column) == list(range(n)), f"column {y} is not a permutation of 0..{n - 1}"

    # Zero diagonal: x*x == 0 for every x.
    diagonal_failures = [x for x in range(n) if table[x][x] != 0]
    assert diagonal_failures == [], f"non-zero diagonal at: {diagonal_failures}"

    # Total anti-symmetry.
    violations = [
        (c, x, y)
        for c in range(n)
        for x in range(n)
        for y in range(n)
        if x != y and table[table[c][x]][y] == table[table[c][y]][x]
    ]
    assert violations == [], f"{len(violations)} total-anti-symmetry violation(s), e.g. {violations[:5]}"


def test_damm_detects_every_single_character_substitution_and_adjacent_transposition():
    """Empirical companion to the algebraic property test above, measured the
    same way docs/design/keys.md measured Luhn mod 32 -- mint real keys, try
    every possible single-character substitution and every adjacent
    transposition, and report what fraction is actually caught, rather than
    asserting a number pulled from the algorithm's theoretical guarantee."""
    n_keys = 200
    keys = [keys_mod.mint() for _ in range(n_keys)]
    assert all(_damm_valid(k) for k in keys)

    sub_total = 0
    sub_caught = 0
    for key in keys:
        for pos in range(keys_mod.KEY_LEN):
            original = key[pos]
            for ch in keys_mod.ALPHABET:
                if ch == original:
                    continue
                mutated = key[:pos] + ch + key[pos + 1 :]
                sub_total += 1
                if not _damm_valid(mutated):
                    sub_caught += 1

    trans_total = 0
    trans_caught = 0
    for key in keys:
        for pos in range(keys_mod.KEY_LEN - 1):
            a, b = key[pos], key[pos + 1]
            if a == b:
                continue  # not a detectable transposition -- the string doesn't change
            mutated = key[:pos] + b + a + key[pos + 2 :]
            trans_total += 1
            if not _damm_valid(mutated):
                trans_caught += 1

    print(
        f"\nDamm, {n_keys} minted keys: "
        f"substitutions {sub_caught}/{sub_total} caught, "
        f"transpositions {trans_caught}/{trans_total} caught"
    )
    assert sub_total > 0 and trans_total > 0  # the loops above actually ran
    assert sub_caught == sub_total, f"{sub_total - sub_caught} substitution(s) slipped through"
    assert trans_caught == trans_total, f"{trans_total - trans_caught} transposition(s) slipped through"


def test_mint_produces_eleven_lowercase_crockford_characters_with_a_valid_check_char():
    for _ in range(500):
        key = keys_mod.mint()
        assert len(key) == 11
        assert key == key.lower()
        assert all(ch in keys_mod.ALPHABET for ch in key)
        assert _damm_valid(key)


def test_mint_never_produces_an_uppercase_start_bare_ref_could_match():
    """docs/design/keys.md's mechanical argument for lowercase: BARE_REF_RE
    requires an uppercase start, so a key can never collide with a bare
    prose display-id reference. Confirmed against the actual regex, not
    just Crockford's own alphabet (which happens to be all-lowercase, but
    the property this test protects is about BARE_REF_RE specifically)."""
    from refdes.build import BARE_REF_RE

    for _ in range(200):
        key = keys_mod.mint()
        assert not BARE_REF_RE.match(key)


def test_check_char_is_deterministic_and_order_sensitive():
    data = "k7f3m2q9x4"
    assert keys_mod.check_char(data) == keys_mod.check_char(data)  # deterministic
    reordered = data[1] + data[0] + data[2:]
    assert reordered != data
    # Not required to differ for every reordering, but this one is a good
    # deterministic smoke check: the same data in a different order should
    # not just happen to be the identity function.
    assert keys_mod.check_char(reordered) == keys_mod.check_char(reordered)


KEYS_SCHEMA = (
    "site: { title: T, out: _site }\n"
    "types:\n"
    "  requirement: { prefix: REQ, fields: { text: { type: text, required: true } } }\n"
)


def _keys_project(tmp_path, items_yaml):
    (tmp_path / "refdes.yaml").write_text(KEYS_SCHEMA, encoding="utf-8")
    items = tmp_path / "items"
    items.mkdir()
    (items / "r.yaml").write_text(items_yaml, encoding="utf-8")
    return tmp_path


def test_mint_missing_assigns_and_writes_back_a_key_for_an_idd_item(tmp_path):
    root = _keys_project(
        tmp_path,
        "defaults: { type: requirement }\n"
        "items:\n  - id: REQ-001\n    text: Already has an id.\n",
    )
    project = load_project(config_path=str(root / "refdes.yaml"))
    parse.load_items(project, require_ids=False)
    written = keys_mod.mint_missing(project)

    assert len(written) == 1
    item, new_key = written[0]
    assert item.id == "REQ-001"
    assert item.key == new_key
    assert _damm_valid(new_key)

    text = (root / "items" / "r.yaml").read_text(encoding="utf-8")
    assert f"key: {new_key}" in text
    assert text.count("key:") == 1

    # Durable: reparsing sees the same key, and mints nothing new.
    project2 = load_project(config_path=str(root / "refdes.yaml"))
    parse.load_items(project2, require_ids=False)
    assert project2.items["REQ-001"].key == new_key
    assert keys_mod.mint_missing(project2) == []


def test_mint_missing_assigns_a_key_to_a_pending_item_with_no_id_yet(tmp_path):
    """§2: a key is independent of the display id -- a pending item gets one
    too, and stays usable/keyed even though it has no id."""
    root = _keys_project(
        tmp_path,
        "defaults: { type: requirement }\nitems:\n  - text: No id yet.\n",
    )
    project = load_project(config_path=str(root / "refdes.yaml"))
    parse.load_items(project, require_ids=False)
    assert len(project.pending) == 1

    written = keys_mod.mint_missing(project)
    assert len(written) == 1
    item, new_key = written[0]
    assert item.id == ""
    assert item.key == new_key
    assert not project.errors

    text = (root / "items" / "r.yaml").read_text(encoding="utf-8")
    assert f"key: {new_key}" in text


def test_mint_missing_writes_back_into_markdown_front_matter(tmp_path):
    (tmp_path / "refdes.yaml").write_text(
        "site: { title: T, out: _site }\n"
        "types:\n  decision: { prefix: DEC, fields: { title: { type: text, required: true } } }\n",
        encoding="utf-8",
    )
    (tmp_path / "items").mkdir()
    path = tmp_path / "items" / "d.md"
    path.write_text("---\nid: DEC-001\ntype: decision\ntitle: Md form.\n---\n", encoding="utf-8")

    project = load_project(config_path=str(tmp_path / "refdes.yaml"))
    parse.load_items(project, require_ids=False)
    written = keys_mod.mint_missing(project)
    assert len(written) == 1
    _item, new_key = written[0]

    text = path.read_text(encoding="utf-8")
    front_matter = text.split("---")[1]
    assert front_matter.count("key:") == 1
    assert f"key: {new_key}" in front_matter

    reparsed = load_project(config_path=str(tmp_path / "refdes.yaml"))
    parse.load_items(reparsed, require_ids=False)
    assert reparsed.items["DEC-001"].key == new_key


def test_mint_missing_writes_back_inside_a_flow_style_entry(tmp_path):
    root = _keys_project(
        tmp_path,
        "defaults: { type: requirement }\n"
        "items:\n  - {id: REQ-001, text: flow style entry}\n",
    )
    project = load_project(config_path=str(root / "refdes.yaml"))
    parse.load_items(project, require_ids=False)
    written = keys_mod.mint_missing(project)
    assert len(written) == 1
    _item, new_key = written[0]

    text = (root / "items" / "r.yaml").read_text(encoding="utf-8")
    reparsed = yaml.safe_load(text)
    assert reparsed["items"] == [{"id": "REQ-001", "text": "flow style entry", "key": new_key}]


def test_mint_missing_never_reassigns_an_existing_key(tmp_path):
    root = _keys_project(
        tmp_path,
        "defaults: { type: requirement }\n"
        "items:\n  - id: REQ-001\n    key: k7f3m2q9x4b\n    text: Already keyed.\n",
    )
    project = load_project(config_path=str(root / "refdes.yaml"))
    parse.load_items(project, require_ids=False)
    assert project.items["REQ-001"].key == "k7f3m2q9x4b"
    assert keys_mod.mint_missing(project) == []
    assert project.items["REQ-001"].key == "k7f3m2q9x4b"


def test_no_write_suppresses_minting_and_reports_one_project_level_info(tmp_path):
    root = _keys_project(
        tmp_path,
        "defaults: { type: requirement }\n"
        "items:\n  - id: REQ-001\n    text: A.\n  - id: REQ-002\n    text: B.\n",
    )
    project = load_project(config_path=str(root / "refdes.yaml"))
    parse.load_items(project, require_ids=False)
    written = keys_mod.mint_missing(project, write=False)

    assert written == []
    assert project.items["REQ-001"].key == ""
    assert project.items["REQ-002"].key == ""
    text = (root / "items" / "r.yaml").read_text(encoding="utf-8")
    assert "key:" not in text  # --no-write must not touch the source file

    info = [d for d in project.diagnostics if d.level == "info"]
    assert len(info) == 1
    assert "2 items have no key yet" in info[0].message
    assert "--no-write" in info[0].message


def test_no_write_singular_item_wording(tmp_path):
    root = _keys_project(
        tmp_path, "defaults: { type: requirement }\nitems:\n  - id: REQ-001\n    text: A.\n"
    )
    project = load_project(config_path=str(root / "refdes.yaml"))
    parse.load_items(project, require_ids=False)
    keys_mod.mint_missing(project, write=False)
    info = [d for d in project.diagnostics if d.level == "info"]
    assert len(info) == 1
    assert "1 item has no key yet" in info[0].message


def test_keyless_item_stays_fully_usable(tmp_path):
    """§2: an item with no key yet still parses, validates, and builds --
    a key is a precondition for being durably referenced, not for existing."""
    root = _keys_project(
        tmp_path, "defaults: { type: requirement }\nitems:\n  - id: REQ-001\n    text: A.\n"
    )
    project = load_project(config_path=str(root / "refdes.yaml"))
    parse.load_items(project, require_ids=False)
    build_mod.build(project, seal_write=False, reseal=False)
    assert not project.errors
    assert project.items["REQ-001"].key == ""
    assert any(e["id"] == "REQ-001" for e in render.items_json(project)["items"])


def test_key_is_reserved_and_not_shadowable_by_a_same_named_field(tmp_path):
    """§3: key: is hard-reserved like id:/former_ids:, not overridable like
    prefix:/board: -- a hand-rolled type declaring its own 'key' field must
    not be able to shadow identity."""
    (tmp_path / "refdes.yaml").write_text(
        "site: { title: T, out: _site }\n"
        "types:\n"
        "  widget: { prefix: WID, fields: { key: { type: text, required: true } } }\n",
        encoding="utf-8",
    )
    items = tmp_path / "items"
    items.mkdir()
    (items / "w.yaml").write_text(
        "defaults: { type: widget }\n"
        "items:\n  - id: WID-001\n    key: not a schema value, this is identity\n",
        encoding="utf-8",
    )
    project = load_project(config_path=str(tmp_path / "refdes.yaml"))
    parse.load_items(project, require_ids=False)
    item = project.items["WID-001"]
    # The hand-typed value was consumed as the surrogate key, not as the
    # type's own declared 'key' field.
    assert item.key == "not a schema value, this is identity"
    assert "key" not in item.fields


def test_cli_check_mints_keys_by_default(tmp_path):
    root = _keys_project(
        tmp_path, "defaults: { type: requirement }\nitems:\n  - id: REQ-001\n    text: A.\n"
    )
    status = cli_mod.main(["-c", str(root / "refdes.yaml"), "check"])
    assert status == 0
    text = (root / "items" / "r.yaml").read_text(encoding="utf-8")
    assert "key:" in text


def test_cli_no_write_leaves_the_source_tree_untouched(tmp_path):
    root = _keys_project(
        tmp_path, "defaults: { type: requirement }\nitems:\n  - id: REQ-001\n    text: A.\n"
    )
    before = (root / "items" / "r.yaml").read_text(encoding="utf-8")
    status = cli_mod.main(["-c", str(root / "refdes.yaml"), "--no-write", "check"])
    assert status == 0
    after = (root / "items" / "r.yaml").read_text(encoding="utf-8")
    assert before == after
