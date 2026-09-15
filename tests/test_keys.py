"""keys.

Split out of the original monolithic tests/test_refdes.py.
"""

from __future__ import annotations

from copy import deepcopy

import yaml
from conftest import write_project_config

from refdes import build as build_mod
from refdes import cli as cli_mod
from refdes import keys as keys_mod
from refdes import lifecycle, parse, render
from refdes.schema import load_project

# ------------------------------------------------------------------------- keys
#
# covers §1 (key format), §2 minting, and §6 Layers 1-5 of the corruption
# lint. §5 (hashing) and §3's link-composite expansion have their own section
# further down. `refdes keys adopt` (§7) remains design only.

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
    "link_types:\n"
    "  refines: { inverse: refined_by, label: Refines }\n"
    "types:\n"
    "  requirement:\n"
    "    prefix: REQ\n"
    "    fields: { text: { type: text, required: true } }\n"
    "    links: { refines: [requirement] }\n"
)


def _keys_project(tmp_path, items_yaml):
    write_project_config(tmp_path, KEYS_SCHEMA)
    items = tmp_path / "items"
    items.mkdir()
    (items / "r.yaml").write_text(items_yaml, encoding="utf-8")
    return tmp_path


def _built_keys_project(root):
    project = load_project(config_path=str(root / "refdes-project.yaml"))
    parse.load_items(project)
    build_mod.build(project, seal_write=False, reseal=False)
    return project


def _stamp_keyed_baseline(root, name="rev-a"):
    project = _built_keys_project(root)
    outcome = lifecycle.stamp(project, kind="revision", name=name)
    assert outcome.status == "stamped"
    return project


def _write_key_baseline(root, name, stamped_at, items):
    path = root / ".refdes" / "baselines" / f"{name}.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "kind": "revision",
        "name": name,
        "stamped_at": stamped_at,
        "stamped_by": "tester",
        "refdes_version": "0.0.0-test",
        "items": items,
    }
    with open(path, "w", encoding="utf-8") as fh:
        yaml.safe_dump(data, fh, sort_keys=False)


def test_mint_missing_assigns_and_writes_back_a_key_for_an_idd_item(tmp_path):
    root = _keys_project(
        tmp_path,
        "defaults: { type: requirement }\n"
        "items:\n  - id: REQ-001\n    text: Already has an id.\n",
    )
    project = load_project(config_path=str(root / "refdes-project.yaml"))
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
    project2 = load_project(config_path=str(root / "refdes-project.yaml"))
    parse.load_items(project2, require_ids=False)
    assert project2.item_by_id("REQ-001").key == new_key
    assert keys_mod.mint_missing(project2) == []


def test_mint_missing_assigns_a_key_to_a_pending_item_with_no_id_yet(tmp_path):
    """§2: a key is independent of the display id -- a pending item gets one
    too, and stays usable/keyed even though it has no id."""
    root = _keys_project(
        tmp_path,
        "defaults: { type: requirement }\nitems:\n  - text: No id yet.\n",
    )
    project = load_project(config_path=str(root / "refdes-project.yaml"))
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
    write_project_config(
        tmp_path,
        "site: { title: T, out: _site }\n"
        "types:\n  decision: { prefix: DEC, fields: { title: { type: text, required: true } } }\n",
    )
    (tmp_path / "items").mkdir()
    path = tmp_path / "items" / "d.md"
    path.write_text("---\nid: DEC-001\ntype: decision\ntitle: Md form.\n---\n", encoding="utf-8")

    project = load_project(config_path=str(tmp_path / "refdes-project.yaml"))
    parse.load_items(project, require_ids=False)
    written = keys_mod.mint_missing(project)
    assert len(written) == 1
    _item, new_key = written[0]

    text = path.read_text(encoding="utf-8")
    front_matter = text.split("---")[1]
    assert front_matter.count("key:") == 1
    assert f"key: {new_key}" in front_matter

    reparsed = load_project(config_path=str(tmp_path / "refdes-project.yaml"))
    parse.load_items(reparsed, require_ids=False)
    assert reparsed.item_by_id("DEC-001").key == new_key


def test_mint_missing_writes_back_inside_a_flow_style_entry(tmp_path):
    root = _keys_project(
        tmp_path,
        "defaults: { type: requirement }\n"
        "items:\n  - {id: REQ-001, text: flow style entry}\n",
    )
    project = load_project(config_path=str(root / "refdes-project.yaml"))
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
        "items:\n  - id: REQ-001\n    key: k7f3m2q9x4a\n    text: Already keyed.\n",
    )
    project = load_project(config_path=str(root / "refdes-project.yaml"))
    parse.load_items(project, require_ids=False)
    assert project.item_by_id("REQ-001").key == "k7f3m2q9x4a"
    assert keys_mod.mint_missing(project) == []
    assert project.item_by_id("REQ-001").key == "k7f3m2q9x4a"


def test_no_write_suppresses_minting_and_reports_one_project_level_info(tmp_path):
    root = _keys_project(
        tmp_path,
        "defaults: { type: requirement }\n"
        "items:\n  - id: REQ-001\n    text: A.\n  - id: REQ-002\n    text: B.\n",
    )
    project = load_project(config_path=str(root / "refdes-project.yaml"))
    parse.load_items(project, require_ids=False)
    written = keys_mod.mint_missing(project, write=False)

    assert written == []
    assert project.item_by_id("REQ-001").key == ""
    assert project.item_by_id("REQ-002").key == ""
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
    project = load_project(config_path=str(root / "refdes-project.yaml"))
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
    project = load_project(config_path=str(root / "refdes-project.yaml"))
    parse.load_items(project, require_ids=False)
    build_mod.build(project, seal_write=False, reseal=False)
    assert not project.errors
    assert project.item_by_id("REQ-001").key == ""
    assert any(e["id"] == "REQ-001" for e in render.items_json(project)["items"])


def test_key_is_reserved_and_not_shadowable_by_a_same_named_field(tmp_path):
    """§3: key: is hard-reserved like id:/former_ids:, not overridable like
    prefix:/board: -- a hand-rolled type declaring its own 'key' field must
    not be able to shadow identity."""
    write_project_config(
        tmp_path,
        "site: { title: T, out: _site }\n"
        "types:\n"
        "  widget: { prefix: WID, fields: { key: { type: text, required: true } } }\n",
    )
    items = tmp_path / "items"
    items.mkdir()
    (items / "w.yaml").write_text(
        "defaults: { type: widget }\n"
        "items:\n  - id: WID-001\n    key: not a schema value, this is identity\n",
        encoding="utf-8",
    )
    project = load_project(config_path=str(tmp_path / "refdes-project.yaml"))
    parse.load_items(project, require_ids=False)
    item = project.item_by_id("WID-001")
    # The hand-typed value was consumed as the surrogate key, not as the
    # type's own declared 'key' field.
    assert item.key == "not a schema value, this is identity"
    assert "key" not in item.fields


def test_corruption_lint_rejects_a_key_with_the_wrong_length(tmp_path):
    root = _keys_project(
        tmp_path,
        "defaults: { type: requirement }\n"
        "items:\n  - id: REQ-001\n    key: k7f3m2q9x4\n    text: A.\n",
    )

    project = _built_keys_project(root)

    assert len(project.errors) == 1
    message = project.errors[0].message
    assert "key 'k7f3m2q9x4' is malformed: expected exactly 11 characters" in message
    assert "restore it from git rather than guessing" in message


def test_corruption_lint_rejects_an_uppercase_key_character(tmp_path):
    root = _keys_project(
        tmp_path,
        "defaults: { type: requirement }\n"
        "items:\n  - id: REQ-001\n    key: K7f3m2q9x4b\n    text: A.\n",
    )

    project = _built_keys_project(root)

    assert len(project.errors) == 1
    message = project.errors[0].message
    assert "key 'K7f3m2q9x4b' is malformed" in message
    assert "outside the key alphabet" in message


def test_corruption_lint_rejects_an_excluded_key_letter(tmp_path):
    root = _keys_project(
        tmp_path,
        "defaults: { type: requirement }\n"
        "items:\n  - id: REQ-001\n    key: k7f3i2q9x4b\n    text: A.\n",
    )

    project = _built_keys_project(root)

    assert len(project.errors) == 1
    message = project.errors[0].message
    assert "key 'k7f3i2q9x4b' is malformed" in message
    assert "outside the key alphabet" in message


def test_corruption_lint_rejects_a_check_character_mismatch_with_expected_character(tmp_path):
    root = _keys_project(
        tmp_path,
        "defaults: { type: requirement }\n"
        "items:\n  - id: REQ-001\n    key: k7f3m2q9x4c\n    text: A.\n",
    )

    project = _built_keys_project(root)

    assert len(project.errors) == 1
    message = project.errors[0].message
    assert "key 'k7f3m2q9x4c' is malformed: check character mismatch" in message
    assert "Expected check character 'a'." in message
    assert "restore it from git rather than guessing" in message


def test_corruption_lint_rejects_a_duplicate_key_across_two_items(tmp_path):
    root = _keys_project(
        tmp_path,
        "defaults: { type: requirement }\n"
        "items:\n  - id: REQ-001\n    key: k7f3m2q9x4a\n    text: A.\n",
    )
    (root / "items" / "s.yaml").write_text(
        "defaults: { type: requirement }\n"
        "items:\n  - id: REQ-002\n    key: k7f3m2q9x4a\n    text: B.\n",
        encoding="utf-8",
    )

    project = _built_keys_project(root)

    assert len(project.errors) == 1
    message = project.errors[0].message
    assert "REQ-001" in message
    assert "REQ-002" in message
    assert "items/r.yaml:" in message
    assert "items/s.yaml:" in message
    assert "Delete the key from one of them and rebuild — it will be re-minted." in message


def test_corruption_lint_rejects_an_undeclared_key_without_display_id_fallback(tmp_path):
    root = _keys_project(
        tmp_path,
        "defaults: { type: requirement }\n"
        "items:\n"
        "  - id: REQ-001\n    key: k7f3m2q9x4a\n    text: Real target.\n"
        "  - id: REQ-002\n    key: 00000000000\n    text: Source.\n"
        "    refines: [REQ-001@k2p9w3x1r7s]\n",
    )

    project = _built_keys_project(root)

    assert len(project.errors) == 1
    message = project.errors[0].message
    assert "refines points at key 'k2p9w3x1r7s' (labelled REQ-001)" in message
    assert "which no item declares" in message
    assert project.item_by_id("REQ-002").resolved_links == {}
    assert project.item_by_id("REQ-001").backlinks == {}


def test_corruption_lint_rejects_a_malformed_link_target_as_corruption(tmp_path):
    root = _keys_project(
        tmp_path,
        "defaults: { type: requirement }\n"
        "items:\n"
        "  - id: REQ-001\n    key: k7f3m2q9x4a\n    text: Real target.\n"
        "  - id: REQ-002\n    key: 00000000000\n    text: Source.\n"
        "    refines: [REQ-001@k2p9w3x1r7]\n",
    )

    project = _built_keys_project(root)

    assert len(project.errors) == 1
    message = project.errors[0].message
    assert "key 'k2p9w3x1r7' in refines target (labelled REQ-001) is malformed" in message
    assert "expected exactly 11 characters" in message
    assert "restore it from git rather than guessing" in message
    assert "which no item declares" not in message


def test_corruption_lint_accepts_valid_minted_keys_and_a_resolving_link(tmp_path):
    target_key = keys_mod.mint()
    source_key = keys_mod.mint()
    root = _keys_project(
        tmp_path,
        "defaults: { type: requirement }\n"
        "items:\n"
        f"  - id: REQ-001\n    key: {target_key}\n    text: Target.\n"
        f"  - id: REQ-002\n    key: {source_key}\n    text: Source.\n"
        f"    refines: [REQ-001@{target_key}]\n",
    )

    project = _built_keys_project(root)

    assert not project.errors
    assert project.item_by_id("REQ-002").resolved_links["refines"] == ["REQ-001"]


def test_writable_check_refuses_to_remint_a_key_deleted_from_a_baselined_item(
    tmp_path, capsys
):
    old_key = keys_mod.mint()
    root = _keys_project(
        tmp_path,
        "defaults: { type: requirement }\n"
        f"items:\n  - id: REQ-001\n    key: {old_key}\n    text: Same item.\n",
    )
    project = _stamp_keyed_baseline(root, "rev-a")
    assert project.item_by_id("REQ-001").key == old_key
    baseline = lifecycle.load_baseline(project, "rev-a")
    assert baseline.items["REQ-001"]["key"] == old_key

    path = root / "items" / "r.yaml"
    path.write_text(
        path.read_text(encoding="utf-8").replace(f"    key: {old_key}\n", ""),
        encoding="utf-8",
    )
    status = cli_mod.main(["-c", str(root / "refdes-project.yaml"), "check"])
    captured = capsys.readouterr()

    # Decision 2026-09-15: the key is *not* re-minted during load, so the
    # evidence survives and Layer 4 says "key deleted", not "key changed".
    reparsed = load_project(config_path=str(root / "refdes-project.yaml"))
    parse.load_items(reparsed)
    assert reparsed.item_by_id("REQ-001").key == ""
    assert status == 1
    assert "key deleted since baseline 'rev-a'" in captured.err
    assert "key changed" not in captured.err
    assert old_key in captured.err
    assert f"`key: {old_key}`" in captured.err


def test_baseline_lint_errors_when_key_deleted_under_no_write(tmp_path, capsys):
    old_key = keys_mod.mint()
    root = _keys_project(
        tmp_path,
        "defaults: { type: requirement }\n"
        f"items:\n  - id: REQ-001\n    key: {old_key}\n    text: Same item.\n",
    )
    _stamp_keyed_baseline(root, "rev-a")
    path = root / "items" / "r.yaml"
    keyless = path.read_text(encoding="utf-8").replace(f"    key: {old_key}\n", "")
    path.write_text(keyless, encoding="utf-8")

    status = cli_mod.main(
        ["-c", str(root / "refdes-project.yaml"), "--no-write", "check"]
    )
    captured = capsys.readouterr()

    assert status == 1
    assert path.read_text(encoding="utf-8") == keyless
    assert "key deleted since baseline 'rev-a'" in captured.err
    assert old_key in captured.err
    assert "now no key is declared" in captured.err


# --- hand-deleted keys (docs/design/keys.md §6, decision 2026-09-15) ----------
#
# A deleted `key:` line used to be silently re-minted during load, so Layer 4
# reported the misleading "key changed" and the evidence was already gone.
# Now the item is left keyless, warned about at load, and reported as deleted.


def test_writable_check_reports_a_deleted_key_without_reminting(tmp_path, capsys):
    old_key = keys_mod.mint()
    root = _keys_project(
        tmp_path,
        "defaults: { type: requirement }\n"
        f"items:\n  - id: REQ-001\n    key: {old_key}\n    text: Same item.\n",
    )
    _stamp_keyed_baseline(root, "rev-a")
    path = root / "items" / "r.yaml"
    keyless = path.read_text(encoding="utf-8").replace(f"    key: {old_key}\n", "")
    path.write_text(keyless, encoding="utf-8")

    status = cli_mod.main(["-c", str(root / "refdes-project.yaml"), "check"])
    captured = capsys.readouterr()

    # The file is left keyless: no replacement key written over the evidence.
    assert path.read_text(encoding="utf-8") == keyless
    assert status == 1
    assert "key deleted" in captured.err
    assert "key changed" not in captured.err
    assert old_key in captured.err
    assert "baseline 'rev-a'" in captured.err
    assert f"key: {old_key}" in captured.err
    assert "new display id" in captured.err
    # The remedy names the item's start, not a line to insert at: an item is a
    # YAML list entry, so "add this line at N" would break the file.
    assert "items/r.yaml:3" in captured.err
    assert "alongside its id:" in captured.err
    assert "WARNING" in captured.out


def test_restoring_the_deleted_key_clears_the_deleted_key_error(tmp_path, capsys):
    old_key = keys_mod.mint()
    root = _keys_project(
        tmp_path,
        "defaults: { type: requirement }\n"
        f"items:\n  - id: REQ-001\n    key: {old_key}\n    text: Same item.\n",
    )
    _stamp_keyed_baseline(root, "rev-a")
    path = root / "items" / "r.yaml"
    path.write_text(
        path.read_text(encoding="utf-8").replace(f"    key: {old_key}\n", ""),
        encoding="utf-8",
    )
    assert cli_mod.main(["-c", str(root / "refdes-project.yaml"), "check"]) == 1

    path.write_text(
        path.read_text(encoding="utf-8").replace(
            "id: REQ-001\n", f"id: REQ-001\n    key: {old_key}\n"
        ),
        encoding="utf-8",
    )
    capsys.readouterr()
    status = cli_mod.main(["-c", str(root / "refdes-project.yaml"), "check"])
    captured = capsys.readouterr()

    assert status == 0
    assert "key deleted" not in captured.out + captured.err
    assert path.read_text(encoding="utf-8").count("key:") == 1


def test_a_new_display_id_mints_a_fresh_key_for_a_replacement_item(tmp_path, capsys):
    old_key = keys_mod.mint()
    root = _keys_project(
        tmp_path,
        "defaults: { type: requirement }\n"
        f"items:\n  - id: REQ-001\n    key: {old_key}\n    text: Same item.\n",
    )
    _stamp_keyed_baseline(root, "rev-a")
    path = root / "items" / "r.yaml"
    path.write_text(
        path.read_text(encoding="utf-8")
        .replace(f"    key: {old_key}\n", "")
        .replace("id: REQ-001", "id: REQ-002"),
        encoding="utf-8",
    )

    status = cli_mod.main(["-c", str(root / "refdes-project.yaml"), "check"])
    captured = capsys.readouterr()

    assert status == 0
    assert "key deleted" not in captured.out + captured.err
    reparsed = load_project(config_path=str(root / "refdes-project.yaml"))
    parse.load_items(reparsed)
    new_key = reparsed.item_by_id("REQ-002").key
    assert new_key and new_key != old_key
    assert f"key: {new_key}" in path.read_text(encoding="utf-8")


def test_a_keyless_item_with_no_record_is_minted_silently(tmp_path, capsys):
    root = _keys_project(
        tmp_path,
        "defaults: { type: requirement }\nitems:\n  - id: REQ-001\n    text: New.\n",
    )

    status = cli_mod.main(["-c", str(root / "refdes-project.yaml"), "check"])
    captured = capsys.readouterr()

    assert status == 0
    assert "key deleted" not in captured.out + captured.err
    assert "no key is declared" not in captured.out + captured.err
    text = (root / "items" / "r.yaml").read_text(encoding="utf-8")
    assert "key:" in text


def test_a_key_keyed_seal_detects_a_deleted_key_without_a_baseline(tmp_path, capsys):
    old_key = keys_mod.mint()
    root = _keys_project(
        tmp_path,
        "defaults: { type: requirement }\n"
        f"items:\n  - id: REQ-001\n    key: {old_key}\n    text: Same item.\n",
    )
    seals = root / ".refdes"
    seals.mkdir()
    (seals / "log-seal.yaml").write_text(
        yaml.safe_dump({"sealed": {old_key: {"id": "REQ-001", "hash": "x"}}}),
        encoding="utf-8",
    )
    path = root / "items" / "r.yaml"
    keyless = path.read_text(encoding="utf-8").replace(f"    key: {old_key}\n", "")
    path.write_text(keyless, encoding="utf-8")

    status = cli_mod.main(["-c", str(root / "refdes-project.yaml"), "check"])
    captured = capsys.readouterr()

    assert status == 1
    assert path.read_text(encoding="utf-8") == keyless
    assert "key deleted" in captured.err
    assert old_key in captured.err
    assert "log-seal.yaml" in captured.err


def test_the_remedy_points_a_markdown_item_at_its_front_matter(tmp_path, capsys):
    old_key = keys_mod.mint()
    root = _keys_project(tmp_path, "items: []\n")
    (root / "items" / "r.md").write_text(
        f"---\nid: REQ-001\nkey: {old_key}\ntype: requirement\n---\nSame item.\n",
        encoding="utf-8",
    )
    _stamp_keyed_baseline(root, "rev-a")
    path = root / "items" / "r.md"
    path.write_text(
        path.read_text(encoding="utf-8").replace(f"key: {old_key}\n", ""),
        encoding="utf-8",
    )

    cli_mod.main(["-c", str(root / "refdes-project.yaml"), "--no-write", "check"])
    captured = capsys.readouterr()

    assert "key deleted" in captured.err
    assert "items/r.md:2" in captured.err
    assert "in its front matter" in captured.err


def test_disagreeing_records_are_both_named(tmp_path, capsys):
    baseline_key = keys_mod.mint()
    seal_key = keys_mod.mint()
    root = _keys_project(
        tmp_path,
        "defaults: { type: requirement }\n"
        f"items:\n  - id: REQ-001\n    key: {baseline_key}\n    text: Same item.\n",
    )
    _stamp_keyed_baseline(root, "rev-a")
    seals = root / ".refdes"
    (seals / "log-seal.yaml").write_text(
        yaml.safe_dump({"sealed": {seal_key: {"id": "REQ-001", "hash": "x"}}}),
        encoding="utf-8",
    )
    path = root / "items" / "r.yaml"
    path.write_text(
        path.read_text(encoding="utf-8").replace(f"    key: {baseline_key}\n", ""),
        encoding="utf-8",
    )

    cli_mod.main(["-c", str(root / "refdes-project.yaml"), "--no-write", "check"])
    captured = capsys.readouterr()

    assert "records disagree" in captured.out + captured.err
    assert seal_key in captured.out + captured.err
    assert baseline_key in captured.out + captured.err


def test_a_membership_record_detects_a_deleted_key(tmp_path, capsys):
    old_key = keys_mod.mint()
    root = _keys_project(
        tmp_path,
        "defaults: { type: requirement }\n"
        f"items:\n  - id: REQ-001\n    key: {old_key}\n    text: Same item.\n",
    )
    boards = root / ".refdes"
    boards.mkdir()
    (boards / "boards.yaml").write_text(
        yaml.safe_dump({"boards": {old_key: {"id": "REQ-001", "board": ""}}}),
        encoding="utf-8",
    )
    path = root / "items" / "r.yaml"
    keyless = path.read_text(encoding="utf-8").replace(f"    key: {old_key}\n", "")
    path.write_text(keyless, encoding="utf-8")

    status = cli_mod.main(
        ["-c", str(root / "refdes-project.yaml"), "--no-write", "check"]
    )
    captured = capsys.readouterr()

    assert status == 1
    assert "key deleted" in captured.err
    assert "membership manifest" in captured.err


def test_baseline_lint_allows_ordinary_display_id_rename_with_same_key(tmp_path):
    key = keys_mod.mint()
    root = _keys_project(
        tmp_path,
        "defaults: { type: requirement }\n"
        f"items:\n  - id: REQ-001\n    key: {key}\n    text: Same item.\n",
    )
    _stamp_keyed_baseline(root)
    path = root / "items" / "r.yaml"
    path.write_text(
        path.read_text(encoding="utf-8").replace("id: REQ-001", "id: REQ-002"),
        encoding="utf-8",
    )

    project = _built_keys_project(root)

    assert not any("key changed" in d.message or "key deleted" in d.message
                   for d in project.errors)


def test_baseline_lint_allows_replacement_at_same_position_with_same_title(tmp_path):
    old_key = keys_mod.mint()
    new_key = keys_mod.mint()
    root = _keys_project(
        tmp_path,
        "defaults: { type: requirement }\n"
        f"items:\n  - id: REQ-001\n    key: {old_key}\n    text: Same title.\n",
    )
    _stamp_keyed_baseline(root)
    path = root / "items" / "r.yaml"
    replacement = path.read_text(encoding="utf-8")
    replacement = replacement.replace("id: REQ-001", "id: REQ-002")
    replacement = replacement.replace(f"key: {old_key}", f"key: {new_key}")
    path.write_text(replacement, encoding="utf-8")

    project = _built_keys_project(root)

    assert project.item_by_id("REQ-002").source_line == 3
    assert project.item_by_id("REQ-002").title == "Same title."
    assert not any("key changed" in d.message or "key deleted" in d.message
                   for d in project.errors)


def test_baseline_lint_skips_pre_keys_baseline_without_recorded_keys(tmp_path):
    key = keys_mod.mint()
    root = _keys_project(
        tmp_path,
        "defaults: { type: requirement }\n"
        f"items:\n  - id: REQ-001\n    key: {key}\n    text: Current.\n",
    )
    _write_key_baseline(
        root,
        "pre-keys",
        "2026-01-01T00:00:00Z",
        {"REQ-001": {"hash": "legacy", "type": "requirement", "title": "Before keys."}},
    )

    project = _built_keys_project(root)

    assert not any("key changed" in d.message or "key deleted" in d.message
                   for d in project.errors)


def test_audit_infos_for_vanished_key_in_older_baseline_without_check_error(
    tmp_path, capsys
):
    vanished_key = keys_mod.mint()
    current_key = keys_mod.mint()
    root = _keys_project(
        tmp_path,
        "defaults: { type: requirement }\n"
        f"items:\n  - id: REQ-001\n    key: {current_key}\n    text: Current.\n",
    )
    _write_key_baseline(
        root,
        "rev-old",
        "2026-01-01T00:00:00Z",
        {
            "REQ-999": {
                "hash": "old",
                "type": "requirement",
                "title": "Deleted.",
                "hash_format": 2,
                "key": vanished_key,
            }
        },
    )
    _write_key_baseline(
        root,
        "rev-current",
        "2026-02-01T00:00:00Z",
        {
            "REQ-001": {
                "hash": "current",
                "type": "requirement",
                "title": "Current.",
                "hash_format": 2,
                "key": current_key,
            }
        },
    )

    audit_status = cli_mod.main(
        ["-c", str(root / "refdes-project.yaml"), "audit"]
    )
    audit_output = capsys.readouterr()
    assert audit_status == 0
    assert "INFO" in audit_output.out
    assert "older baseline 'rev-old'" in audit_output.out
    assert vanished_key in audit_output.out
    assert "not a build error" in audit_output.out

    check_status = cli_mod.main(
        ["-c", str(root / "refdes-project.yaml"), "check"]
    )
    check_output = capsys.readouterr()
    assert check_status == 0
    assert "rev-old" not in check_output.out + check_output.err
    assert vanished_key not in check_output.out + check_output.err


def test_cli_check_mints_keys_by_default(tmp_path):
    root = _keys_project(
        tmp_path, "defaults: { type: requirement }\nitems:\n  - id: REQ-001\n    text: A.\n"
    )
    status = cli_mod.main(["-c", str(root / "refdes-project.yaml"), "check"])
    assert status == 0
    text = (root / "items" / "r.yaml").read_text(encoding="utf-8")
    assert "key:" in text


def test_cli_no_write_leaves_the_source_tree_untouched(tmp_path):
    root = _keys_project(
        tmp_path, "defaults: { type: requirement }\nitems:\n  - id: REQ-001\n    text: A.\n"
    )
    before = (root / "items" / "r.yaml").read_text(encoding="utf-8")
    status = cli_mod.main(["-c", str(root / "refdes-project.yaml"), "--no-write", "check"])
    assert status == 0
    after = (root / "items" / "r.yaml").read_text(encoding="utf-8")
    assert before == after


def test_mixed_shape_baseline_drives_diff_and_layer_four_lint(tmp_path):
    key_1 = keys_mod.mint()
    key_2 = keys_mod.mint()
    root = _keys_project(
        tmp_path,
        "defaults: { type: requirement }\n"
        "items:\n"
        f"  - id: REQ-001\n    key: {key_1}\n    text: Legacy-shaped.\n"
        f"  - id: REQ-002\n    key: {key_2}\n    text: Key-shaped.\n",
    )
    project = _built_keys_project(root)
    _write_key_baseline(
        root,
        "mixed",
        "2026-01-01T00:00:00Z",
        {
            "REQ-001": {
                "key": key_1,
                "hash": project.item_by_id("REQ-001").content_hash,
                "hash_format": 2,
                "type": "requirement",
                "title": "Legacy-shaped.",
            },
            key_2: {
                "id": "REQ-002",
                "hash": project.item_by_id("REQ-002").content_hash,
                "hash_format": 2,
                "type": "requirement",
                "title": "Key-shaped.",
            },
        },
    )

    project2 = _built_keys_project(root)
    diff = lifecycle.diff_against(project2, lifecycle.load_baseline(project2, "mixed"))
    assert diff.changed == []
    assert diff.added == []
    assert diff.removed == []
    assert lifecycle.stamp(project2, kind="revision", name="mixed").status == "unchanged"
    assert diff.relabelled == []
    assert diff.unchanged_count == 2
    assert not any("key changed" in diagnostic.message for diagnostic in project2.errors)

    replacement_key = keys_mod.mint()
    path = root / "items" / "r.yaml"
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            f"    key: {key_2}\n", f"    key: {replacement_key}\n"
        ),
        encoding="utf-8",
    )
    corrupted = _built_keys_project(root)
    assert any(
        f"key changed since baseline 'mixed': was '{key_2}', now '{replacement_key}'"
        in diagnostic.message
        for diagnostic in corrupted.errors
    )


def test_storage_conversion_conditionally_rekeys_and_reports_uncomparable(tmp_path):
    key_1 = keys_mod.mint()
    key_2 = keys_mod.mint()
    root = _keys_project(
        tmp_path,
        "defaults: { type: requirement }\n"
        "items:\n"
        f"  - id: REQ-001\n    key: {key_1}\n    text: Unchanged.\n"
        f"    refines: [REQ-002@{key_2}]\n"
        f"  - id: REQ-002\n    key: {key_2}\n    text: Changed.\n"
        "  - id: REQ-003\n    text: Keyless.\n",
    )
    project = _built_keys_project(root)
    legacy_hash = build_mod.legacy_hash_for(project.item_by_id("REQ-001"), project)
    assert legacy_hash != project.item_by_id("REQ-001").content_hash
    baseline_items = {
        "REQ-001": {
            "key": key_1,
            "hash": legacy_hash,
            "type": "requirement",
            "title": "Unchanged.",
        },
        "REQ-002": {
            "key": key_2,
            "hash": "stale",
            "hash_format": 2,
            "type": "requirement",
            "title": "Changed.",
        },
        "REQ-003": {
            "hash": project.item_by_id("REQ-003").content_hash,
            "hash_format": 2,
            "type": "requirement",
            "title": "Keyless.",
        },
    }
    seals = {
        "REQ-001": legacy_hash,
        "REQ-002": "stale",
        "REQ-003": project.item_by_id("REQ-003").content_hash,
    }
    original_baseline = deepcopy(baseline_items)
    original_seals = deepcopy(seals)

    plan = keys_mod.plan_surrogate_storage(project, baseline_items, seals)

    assert baseline_items == original_baseline
    assert seals == original_seals
    assert plan.baseline_items[key_1] == {
        "hash": project.item_by_id("REQ-001").content_hash,
        "type": "requirement",
        "title": "Unchanged.",
        "id": "REQ-001",
        "hash_format": build_mod.HASH_FORMAT,
    }
    assert plan.baseline_items["REQ-002"]["hash"] == "stale"
    assert plan.baseline_items["REQ-002"]["hash_format"] == 1
    assert plan.baseline_items["REQ-003"]["hash_format"] == 1
    assert plan.baseline_uncomparable == ["REQ-002", "REQ-003"]
    assert plan.seals[key_1] == {
        "hash": project.item_by_id("REQ-001").content_hash,
        "id": "REQ-001",
        "hash_format": build_mod.HASH_FORMAT,
    }
    assert plan.seals["REQ-002"] == {"hash": "stale", "hash_format": 1}
    assert plan.seals["REQ-003"]["hash_format"] == 1
    assert plan.seal_uncomparable == ["REQ-002", "REQ-003"]


def test_keyed_baseline_rename_is_relabelled_not_removed_and_added(tmp_path, capsys):
    key = keys_mod.mint()
    root = _keys_project(
        tmp_path,
        "defaults: { type: requirement }\n"
        f"items:\n  - id: REQ-001\n    key: {key}\n    text: Same item.\n",
    )
    before = _built_keys_project(root)
    _write_key_baseline(
        root,
        "rev-a",
        "2026-01-01T00:00:00Z",
        {
            key: {
                "id": "REQ-001",
                "hash": before.item_by_id("REQ-001").content_hash,
                "hash_format": 2,
                "type": "requirement",
                "title": "Same item.",
            }
        },
    )
    item_path = root / "items" / "r.yaml"
    item_path.write_text(
        item_path.read_text(encoding="utf-8").replace("id: REQ-001", "id: REQ-009"),
        encoding="utf-8",
    )
    after = _built_keys_project(root)

    diff = lifecycle.diff_against(after, lifecycle.load_baseline(after, "rev-a"))
    assert diff.changed == []
    assert diff.added == []
    assert diff.removed == []
    assert diff.relabelled == [("REQ-001", "REQ-009", key)]
    assert diff.unchanged_count == 0

    cli_mod._print_baseline_diff(diff)
    output = capsys.readouterr().out
    assert "  relabelled 1\n" in output
    assert f"    REQ-001 -> REQ-009   ({key})\n" in output
