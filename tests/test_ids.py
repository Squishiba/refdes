"""ids -- and: bare-numeric expand-and-freeze (finding 8 Part 1), prefix ("type segment") validation (finding 8 Parts 1/2).

Split out of the original monolithic tests/test_refdes.py.
"""

from __future__ import annotations

import os
import shutil
import textwrap

import pytest
import yaml
from conftest import write_project_config
from helpers import NUMERIC_HINT_SCHEMA, REPO, _numeric_hint_project

from refdes import build as build_mod
from refdes import cli as cli_mod
from refdes import ids, parse, render
from refdes.schema import load_project

# ---------------------------------------------------------------------- ids


LIST_FILE = """\
defaults:
  type: requirement
  prefix: REQ-TMP
items:
  - id: REQ-TMP-001
    text: First.
  - text: Inserted at the top later.
  - id: REQ-TMP-002
    text: Second.
"""


@pytest.fixture
def temp_project(tmp_path):
    shutil.copy(os.path.join(REPO, "refdes-project.yaml"), tmp_path / "refdes-project.yaml")
    shutil.copy(os.path.join(REPO, "refdes-schema.yaml"), tmp_path / "refdes-schema.yaml")
    items = tmp_path / "items" / "requirements"
    items.mkdir(parents=True)
    (items / "tmp.yaml").write_text(LIST_FILE, encoding="utf-8")
    return tmp_path


def test_allocation_never_renumbers_existing_items(temp_project):
    project = load_project(config_path=str(temp_project / "refdes-project.yaml"))
    parse.load_items(project, require_ids=False)
    ids.allocate(project)

    text = (temp_project / "items" / "requirements" / "tmp.yaml").read_text(
        encoding="utf-8"
    )
    # The pre-existing IDs keep their numbers; the new item gets the next free one.
    assert "REQ-TMP-001" in text
    assert "REQ-TMP-002" in text
    assert "REQ-TMP-003" in text
    assert text.index("REQ-TMP-003") < text.index("REQ-TMP-002")  # inserted in place


def test_allocated_numbers_are_burned_and_never_reused(temp_project):
    project = load_project(config_path=str(temp_project / "refdes-project.yaml"))
    parse.load_items(project, require_ids=False)
    ids.allocate(project)

    # Delete every item, then add a fresh one: it must not reclaim a burned number.
    (temp_project / "items" / "requirements" / "tmp.yaml").write_text(
        textwrap.dedent(
            """\
            defaults:
              type: requirement
              prefix: REQ-TMP
            items:
              - text: Brand new.
            """
        ),
        encoding="utf-8",
    )
    project2 = load_project(config_path=str(temp_project / "refdes-project.yaml"))
    parse.load_items(project2, require_ids=False)
    assignments = ids.allocate(project2)
    assert assignments[0][1] == "REQ-TMP-004"


def test_id_write_back_fills_bare_id_key_in_place_not_a_second_key(tmp_path):
    """`refdes new` scaffolds a bare `id:` placeholder as the first key. Running
    `refdes id` on it must fill that key in place -- not insert a second `id:` key
    below it. A duplicate key is not a cosmetic wart: YAML resolves a mapping with
    a duplicate key to the *last* occurrence, which is the still-empty original, so
    the item silently looks unallocated again on the very next parse, and a second
    `refdes id` run burns a second id on top of the first without fixing anything."""
    write_project_config(
        tmp_path,
        "site: { title: T, out: _site }\n"
        "types:\n"
        "  requirement: { prefix: REQ, fields: { text: { type: text, required: true } } }\n",
    )
    (tmp_path / "items").mkdir()
    path = tmp_path / "items" / "i.yaml"
    path.write_text(
        "defaults: { type: requirement, prefix: CAN }\n"
        "items:\n"
        "  - id:\n"
        "    text: A can requirement.\n",
        encoding="utf-8",
    )

    project = load_project(config_path=str(tmp_path / "refdes-project.yaml"))
    parse.load_items(project, require_ids=False)
    assignments = ids.allocate(project)
    assert assignments and assignments[0][1] == "CAN-001"

    text = path.read_text(encoding="utf-8")
    assert text.count("id:") == 1, f"expected exactly one 'id:' key, got:\n{text}"
    assert "id: CAN-001" in text

    # Re-parse from disk, the way a second, separate `refdes id` invocation would --
    # this is what actually exposes the corruption: a duplicate key resolves to the
    # *last* one, so a still-broken file looks pending again here.
    project2 = load_project(config_path=str(tmp_path / "refdes-project.yaml"))
    parse.load_items(project2, require_ids=False)
    assert project2.item_by_id("CAN-001") is not None
    assert not project2.pending, "the item must not still look unallocated on reparse"

    # A second run against an already-correct file must be a no-op, not another
    # allocation burning a second id for the same item.
    assignments2 = ids.allocate(project2)
    assert assignments2 == []


def test_id_write_back_fills_bare_id_key_in_place_markdown(tmp_path):
    """Same corruption as the YAML-list form above, but through the front-matter
    insertion path (`insert_into_markdown`), which is even more directly at fault:
    it splices in a new line unconditionally, with no read of what's already on the
    target line at all."""
    write_project_config(
        tmp_path,
        "site: { title: T, out: _site }\n"
        "types:\n"
        "  decision: { prefix: DEC, fields: { title: { type: text, required: true } }, body: {} }\n",
    )
    (tmp_path / "items").mkdir()
    path = tmp_path / "items" / "d.md"
    path.write_text(
        "---\n"
        "id:\n"
        "type: decision\n"
        "title: A decision.\n"
        "---\n"
        "Body text.\n",
        encoding="utf-8",
    )

    project = load_project(config_path=str(tmp_path / "refdes-project.yaml"))
    parse.load_items(project, require_ids=False)
    assignments = ids.allocate(project)
    assert assignments and assignments[0][1] == "DEC-001"

    text = path.read_text(encoding="utf-8")
    front_matter = text.split("---")[1]
    assert front_matter.count("id:") == 1, f"expected exactly one 'id:' key, got:\n{text}"
    assert "id: DEC-001" in front_matter

    project2 = load_project(config_path=str(tmp_path / "refdes-project.yaml"))
    parse.load_items(project2, require_ids=False)
    assert project2.item_by_id("DEC-001") is not None
    assert not project2.pending, "the item must not still look unallocated on reparse"

    assignments2 = ids.allocate(project2)
    assert assignments2 == []


def test_quoted_numeric_id_expands_in_place_no_duplicate_key(tmp_path):
    root = _numeric_hint_project(
        tmp_path,
        "defaults:\n  type: requirement\n  prefix: CAN\n"
        "items:\n  - id: \"042\"\n    text: Legacy number.\n",
    )
    project = load_project(config_path=str(root / "refdes-project.yaml"))
    parse.load_items(project, require_ids=False)
    assignments = ids.allocate(project)
    assert assignments and assignments[0][1] == "CAN-042"

    text = (root / "items" / "r.yaml").read_text(encoding="utf-8")
    assert text.count("id:") == 1, f"expected exactly one 'id:' key, got:\n{text}"
    assert "id: CAN-042" in text


def test_expanded_numeric_id_is_byte_identical_to_a_hand_typed_one(tmp_path):
    """The finding's own hard-won conclusion: once expanded, the stored id is
    exactly as self-contained as a fully hand-typed one -- nothing left for
    check/build to ever resolve live."""
    hand_root = tmp_path / "hand"
    (hand_root / "items").mkdir(parents=True)
    write_project_config(hand_root, NUMERIC_HINT_SCHEMA)
    hand_file = hand_root / "items" / "r.yaml"
    hand_file.write_text(
        "defaults:\n  type: requirement\n  prefix: CAN\n"
        "items:\n  - id: CAN-042\n    text: Same content either way.\n",
        encoding="utf-8",
    )

    exp_root = tmp_path / "expanded"
    (exp_root / "items").mkdir(parents=True)
    write_project_config(exp_root, NUMERIC_HINT_SCHEMA)
    exp_file = exp_root / "items" / "r.yaml"
    exp_file.write_text(
        "defaults:\n  type: requirement\n  prefix: CAN\n"
        "items:\n  - id: \"042\"\n    text: Same content either way.\n",
        encoding="utf-8",
    )
    project = load_project(config_path=str(exp_root / "refdes-project.yaml"))
    parse.load_items(project, require_ids=False)
    ids.allocate(project)

    assert exp_file.read_text(encoding="utf-8") == hand_file.read_text(encoding="utf-8")


def test_quoted_numeric_id_expands_in_markdown_front_matter(tmp_path):
    write_project_config(
        tmp_path,
        "site: { title: T, out: _site }\n"
        "types:\n  decision: { prefix: DEC, fields: { title: { type: text, required: true } } }\n",
    )
    (tmp_path / "items").mkdir()
    path = tmp_path / "items" / "d.md"
    path.write_text('---\nid: "5"\ntype: decision\ntitle: Md form.\n---\n', encoding="utf-8")

    project = load_project(config_path=str(tmp_path / "refdes-project.yaml"))
    parse.load_items(project, require_ids=False)
    assignments = ids.allocate(project)
    assert assignments and assignments[0][1] == "DEC-5"

    text = path.read_text(encoding="utf-8")
    front_matter = text.split("---")[1]
    assert front_matter.count("id:") == 1
    assert "id: DEC-5" in front_matter


def test_quoted_numeric_id_expands_inside_a_flow_style_entry(tmp_path):
    root = _numeric_hint_project(
        tmp_path,
        "defaults:\n  type: requirement\n  prefix: CAN\n"
        'items:\n  - {id: "042", text: flow style entry}\n',
    )
    project = load_project(config_path=str(root / "refdes-project.yaml"))
    parse.load_items(project, require_ids=False)
    ids.allocate(project)

    text = (root / "items" / "r.yaml").read_text(encoding="utf-8")
    reparsed = yaml.safe_load(text)
    assert reparsed["items"] == [{"id": "CAN-042", "text": "flow style entry"}]


# ------------------------------------- a hint that is not the item's first key
#
# The write-back used to look only at the line an item *starts* on when
# deciding whether it already held an `id:`. A hint written under `type:` /
# `title:` -- the ordinary shape, since a hand-written item leads with its
# type -- was therefore missed, and a second `id:` line got spliced in above
# it. YAML resolves a repeated key to the *last* one, so the hint won: the
# item reloaded as `007`, `refdes check` reported "has no prefix yet"
# (parse.py's pending-item diagnostic), and a second `refdes id` refused it
# as a burned-number collision. The hint line must be *replaced* wherever in
# the entry it sits, not shadowed by a new one.


def _hint_project(tmp_path, name, source, *, crlf=False):
    write_project_config(tmp_path, NUMERIC_HINT_SCHEMA)
    items = tmp_path / "items"
    items.mkdir()
    path = items / name
    if crlf:
        path.write_bytes(source.replace("\n", "\r\n").encode("utf-8"))
    else:
        path.write_text(source, encoding="utf-8")
    return tmp_path, path


def _assert_clean_and_idempotent(root, capsys):
    """`refdes check` clean, and a second `refdes id` a no-op. These are the
    two symptoms of the leftover hint: the item reads as unallocated again
    (check), and re-allocating it burns a second id (id)."""
    cfg = str(root / "refdes-project.yaml")
    assert cli_mod.main(["-c", cfg, "check"]) == 0, capsys.readouterr().out

    capsys.readouterr()
    assert cli_mod.main(["-c", cfg, "id"]) == 0
    assert "no items are missing an id" in capsys.readouterr().out

    project = load_project(config_path=cfg)
    parse.load_items(project, require_ids=False)
    assert not project.pending, "the item must not still look unallocated on reparse"
    assert ids.allocate(project) == []


@pytest.mark.parametrize("hint", ["'007'", '"007"'])
def test_markdown_hint_below_other_keys_is_replaced_not_shadowed(tmp_path, capsys, hint):
    root, path = _hint_project(
        tmp_path, "r.md", f"---\ntype: requirement\ntext: Legacy number.\nid: {hint}\n---\nBody.\n"
    )
    assert cli_mod.main(["-c", str(root / "refdes-project.yaml"), "id"]) == 0

    front_matter = path.read_text(encoding="utf-8").split("---")[1]
    assert front_matter.count("id:") == 1, f"expected one 'id:' key, got:\n{front_matter}"
    assert "id: REQ-007" in front_matter
    _assert_clean_and_idempotent(root, capsys)


@pytest.mark.parametrize("hint", ["'007'", '"007"'])
def test_list_hint_below_other_keys_is_replaced_not_shadowed(tmp_path, capsys, hint):
    root, path = _hint_project(
        tmp_path,
        "r.yaml",
        "defaults: { type: requirement }\n"
        f"items:\n  - type: requirement\n    text: Legacy number.\n    id: {hint}\n",
    )
    assert cli_mod.main(["-c", str(root / "refdes-project.yaml"), "id"]) == 0

    text = path.read_text(encoding="utf-8")
    assert text.count("id:") == 1, f"expected one 'id:' key, got:\n{text}"
    assert "id: REQ-007" in text
    _assert_clean_and_idempotent(root, capsys)


def test_crlf_hint_file_is_rewritten_without_touching_its_line_endings(tmp_path, capsys):
    """The hint's own line is replaced; every other byte -- CRLF included --
    is the file's own. Read back as bytes, since text mode would hide a
    translation that the writer is not supposed to make."""
    root, path = _hint_project(
        tmp_path,
        "r.md",
        "---\ntype: requirement\ntext: Legacy number.\nid: '007'\n---\nBody.\n",
        crlf=True,
    )
    assert cli_mod.main(["-c", str(root / "refdes-project.yaml"), "id"]) == 0

    raw = path.read_bytes()
    assert b"id: REQ-007\r\n" in raw
    assert b"'007'" not in raw
    assert b"\n" not in raw.replace(b"\r\n", b""), "a lone LF crept in"
    _assert_clean_and_idempotent(root, capsys)


def test_unquoted_hint_is_refused_and_the_file_is_never_rewritten(tmp_path, capsys):
    """The unquoted spelling of a numeric hint, end to end. YAML hands
    `id: 007` to the parser as an int (007 is octal), so it is refused rather
    than expanded -- which means an unquoted hint can never reach the
    write-back. What must hold is that the file is left exactly as written:
    no `id:` line is inserted beside it, and nothing is burned."""
    root, path = _hint_project(
        tmp_path,
        "r.md",
        "---\ntype: requirement\ntext: Unquoted.\nid: 007\n---\nBody.\n",
    )
    before = path.read_bytes()

    # Exit 1: the parse-time refusal is the only diagnostic there is, and it
    # is an error precisely so the run cannot pass as a clean no-op.
    assert cli_mod.main(["-c", str(root / "refdes-project.yaml"), "id"]) == 1
    assert path.read_bytes() == before
    assert not (root / ".refdes" / "ids.yaml").exists()
    # The diagnostic lands on stderr (see the neighbouring "unquoted number"
    # test, which reads it off the project's own error list instead).
    assert "octal" in capsys.readouterr().err


# ------------------------------- where the widened search must NOT reach
#
# The fix widened the search for an existing key line from "the line the item
# starts on" to the whole entry. These pin the boundaries that widening is
# only safe inside: another item's key, a nested mapping's key, and a block
# scalar's body all sit at other columns and are never this item's own key.


@pytest.mark.parametrize("hint", ["'007'", '"007"', "007"])
def test_markdown_writer_replaces_the_hint_line_wherever_it_sits(hint):
    """`insert_into_markdown` matches the hint as written -- single-quoted,
    double-quoted, or bare -- and replaces that line, wherever in the block
    it is."""
    lines = ["---", "type: requirement", f"id: {hint}", "text: x", "---"]
    assert ids.insert_into_markdown(lines, 2, "id: REQ-007", old_value="007") == [
        "---", "type: requirement", "id: REQ-007", "text: x", "---",
    ]


@pytest.mark.parametrize("hint", ["'007'", '"007"', "007"])
def test_list_writer_replaces_the_hint_line_wherever_it_sits(hint):
    lines = [
        "items:", "  - type: requirement", f"    id: {hint}", "    text: x",
        "  - text: y",
    ]
    assert ids.insert_into_list(lines, 2, "id", "REQ-007", old_value="007") == [
        "items:", "  - type: requirement", "    id: REQ-007", "    text: x",
        "  - text: y",
    ]


def test_list_writer_handles_a_shallow_first_key_and_deeper_continuations():
    """`LIST_ENTRY_RE` yields the entry's *minimum* column, but a hand-written
    entry may align its keys further right -- `- type: ...` followed by
    `    id: '007'` is valid YAML and the ordinary shape."""
    lines = ["items:", "  - type: requirement", "    id: '007'", "    text: x"]
    assert ids.insert_into_list(lines, 2, "id", "REQ-007", old_value="007") == [
        "items:", "  - type: requirement", "    id: REQ-007", "    text: x",
    ]


def test_markdown_writer_does_not_reach_into_the_next_block_or_a_nested_key():
    lines = ["---", "type: requirement", "meta:", "  id:", "---"]
    assert ids.insert_into_markdown(lines, 2, "id: REQ-001") == [
        "---", "id: REQ-001", "type: requirement", "meta:", "  id:", "---",
    ]

    two = [
        "---", "type: requirement", "text: a", "---", "Body.",
        "---", "type: requirement", "id:", "text: b", "---",
    ]
    out = ids.insert_into_markdown(two, 2, "id: REQ-001")
    assert out[1] == "id: REQ-001"
    assert out[8] == "id:", "the next item's own placeholder must be left alone"


def test_markdown_writer_does_not_reach_into_a_block_scalar_body():
    """The one place a same-spelling line really can appear: a `|` value's
    body is text, not front matter, and rewriting it would edit the item's
    prose. YAML requires a block scalar's body to sit past its key's column,
    which is exactly the restriction that keeps it out of reach."""
    lines = ["---", "type: requirement", "text: |", "  id: '007'", "---"]
    assert ids.insert_into_markdown(lines, 2, "id: REQ-007", old_value="007") == [
        "---", "id: REQ-007", "type: requirement", "text: |", "  id: '007'", "---",
    ]


def test_list_writer_does_not_reach_the_next_entry_or_a_nested_key():
    lines = ["items:", "  - type: requirement", "    meta:", "      id:", "    text: x"]
    assert ids.insert_into_list(lines, 2, "id", "REQ-001") == [
        "items:", "  - id: REQ-001", "    type: requirement", "    meta:", "      id:",
        "    text: x",
    ]

    two = [
        "items:", "  - type: requirement", "    text: a",
        "  - id:", "    text: b",
    ]
    out = ids.insert_into_list(two, 2, "id", "REQ-001")
    assert out[1] == "  - id: REQ-001"
    assert out[4] == "  - id:", "the next entry's own placeholder must be left alone"


def test_unquoted_numeric_id_is_refused_not_silently_mangled(tmp_path):
    """YAML reads an unquoted leading zero as octal (042 -> 34); trusting it
    would risk freezing the wrong id forever, so it's refused rather than
    expanded -- and, critically, must not be treated as an ordinary pending
    item either (see the next test)."""
    root = _numeric_hint_project(
        tmp_path,
        "defaults:\n  type: requirement\n  prefix: CAN\n"
        "items:\n  - id: 042\n    text: Unquoted, dangerous.\n",
    )
    project = load_project(config_path=str(root / "refdes-project.yaml"))
    parse.load_items(project, require_ids=False)
    assert any(
        "unquoted number" in d.message and "octal" in d.message for d in project.errors
    )


def test_unquoted_numeric_id_is_never_allocated_into(tmp_path):
    """The bug this guards against: an item that failed _resolve_id_value's
    safety check still has item.id == "" like a genuinely blank item -- if it
    entered project.pending, `refdes id` would allocate a fresh, unrelated id
    and write it in *alongside* the bad value (duplicate key, Part 0's bug
    again) instead of leaving the file untouched for a human to fix."""
    root = _numeric_hint_project(
        tmp_path,
        "defaults:\n  type: requirement\n  prefix: CAN\n"
        "items:\n  - id: 042\n    text: Unquoted, dangerous.\n",
    )
    before = (root / "items" / "r.yaml").read_text(encoding="utf-8")

    project = load_project(config_path=str(root / "refdes-project.yaml"))
    parse.load_items(project, require_ids=False)
    assert project.pending == []

    assignments = ids.allocate(project)
    assert assignments == []
    after = (root / "items" / "r.yaml").read_text(encoding="utf-8")
    assert after == before
    ledger_path = root / ".refdes" / "ids.yaml"
    assert not ledger_path.exists(), "no id may be burned for a rejected value"


def test_numeric_hint_freezes_the_authors_number_not_the_next_sequential_one(tmp_path):
    root = _numeric_hint_project(
        tmp_path,
        "defaults:\n  type: requirement\n  prefix: CAN\n"
        "items:\n"
        "  - id: CAN-002\n    text: Already at 2.\n"
        "  - id: \"050\"\n    text: Matches legacy numbering.\n"
        "  - id:\n    text: Freshly authored, no opinion.\n",
    )
    project = load_project(config_path=str(root / "refdes-project.yaml"))
    parse.load_items(project, require_ids=False)
    assignments = ids.allocate(project)
    by_text = {item.fields["text"]: new_id for item, new_id in assignments}
    assert by_text["Matches legacy numbering."] == "CAN-050"
    # The fresh item gets the next number *after* the frozen one, not 003.
    assert by_text["Freshly authored, no opinion."] == "CAN-051"


def test_numeric_hint_colliding_with_a_live_id_is_refused(tmp_path):
    root = _numeric_hint_project(
        tmp_path,
        "defaults:\n  type: requirement\n  prefix: CAN\n"
        "items:\n"
        "  - id: CAN-005\n    text: Already exists.\n"
        "  - id: \"5\"\n    text: Collides with above.\n",
    )
    before = (root / "items" / "r.yaml").read_text(encoding="utf-8")
    project = load_project(config_path=str(root / "refdes-project.yaml"))
    parse.load_items(project, require_ids=False)
    assignments = ids.allocate(project)
    assert assignments == []
    assert any("already used or was burned" in d.message for d in project.errors)
    assert (root / "items" / "r.yaml").read_text(encoding="utf-8") == before


def test_numeric_hint_colliding_with_a_burned_but_deleted_id_is_refused(tmp_path):
    """Burned ids are permanent even after the item that held one is deleted
    -- a numeric hint must respect that, not just check against currently
    live items."""
    root = _numeric_hint_project(
        tmp_path,
        "defaults:\n  type: requirement\n  prefix: CAN\n"
        "items:\n  - id: \"5\"\n    text: Wants a retired number.\n",
    )
    (root / ".refdes").mkdir()
    (root / ".refdes" / "ids.yaml").write_text(
        "burned:\n  CAN: 5\nallocated: []\n", encoding="utf-8"
    )
    project = load_project(config_path=str(root / "refdes-project.yaml"))
    parse.load_items(project, require_ids=False)
    assignments = ids.allocate(project)
    assert assignments == []
    assert any("already used or was burned" in d.message for d in project.errors)


def test_index_exposes_next_free_id_per_prefix(tmp_path):
    """Finding 10 Part 1: an editor completing a partially-typed id needs
    the next free number per prefix, unioned across live items and the
    ledger's burned/allocated history -- exactly what high_water() already
    computes, one more than its own reported maximum."""
    root = _numeric_hint_project(
        tmp_path,
        "defaults:\n  type: requirement\n  prefix: CAN\n"
        "items:\n  - id: CAN-001\n    text: Live.\n",
    )
    (root / ".refdes").mkdir()
    (root / ".refdes" / "ids.yaml").write_text(
        "burned:\n  CAN: 4\nallocated: [CAN-001]\n", encoding="utf-8"
    )
    project = load_project(config_path=str(root / "refdes-project.yaml"))
    parse.load_items(project, require_ids=False)
    build_mod.build(project, seal_write=False, reseal=False)
    payload = render.items_json(project)
    assert payload["next_ids"] == {"CAN": 5}


def test_numeric_hint_two_items_requesting_the_same_number_only_one_wins(tmp_path):
    root = _numeric_hint_project(
        tmp_path,
        "defaults:\n  type: requirement\n  prefix: CAN\n"
        "items:\n"
        "  - id: \"9\"\n    text: First claim.\n"
        "  - id: \"9\"\n    text: Second claim, same number.\n",
    )
    project = load_project(config_path=str(root / "refdes-project.yaml"))
    parse.load_items(project, require_ids=False)
    assignments = ids.allocate(project)
    assert len(assignments) == 1
    assert assignments[0][0].fields["text"] == "First claim."
    assert any("already used or was burned" in d.message for d in project.errors)


def test_cli_id_reports_a_numeric_hint_collision_and_exits_nonzero(tmp_path):
    root = _numeric_hint_project(
        tmp_path,
        "defaults:\n  type: requirement\n  prefix: CAN\n"
        "items:\n"
        "  - id: CAN-005\n    text: Already exists.\n"
        "  - id: \"5\"\n    text: Collides.\n",
    )
    status = cli_mod.main(["-c", str(root / "refdes-project.yaml"), "id"])
    assert status == 1


def test_cli_id_succeeds_and_reports_zero_when_nothing_is_pending(tmp_path):
    root = _numeric_hint_project(
        tmp_path,
        "defaults:\n  type: requirement\n  prefix: CAN\n"
        "items:\n  - id: CAN-001\n    text: Already has an id.\n",
    )
    assert cli_mod.main(["-c", str(root / "refdes-project.yaml"), "id"]) == 0


# --------------------------------------- prefix ("type segment") validation (finding 8 Parts 1/2)


def test_prefix_mismatch_from_a_defaults_override_is_the_documented_warning(tmp_path):
    root = _numeric_hint_project(
        tmp_path,
        "defaults:\n  type: requirement\n  prefix: CAN\n"
        "items:\n  - id: CNA-001\n    text: Typo in the prefix.\n",
    )
    project = load_project(config_path=str(root / "refdes-project.yaml"))
    parse.load_items(project, require_ids=False)
    ids.validate_prefixes(project)
    message = next(d.message for d in project.warnings if "CNA-001" in d.message)
    assert message == "id 'CNA-001' does not match this item's prefix 'CAN' (from defaults:)"


def test_prefix_mismatch_against_the_types_own_default_names_the_type(tmp_path):
    root = _numeric_hint_project(
        tmp_path,
        "items:\n  - id: XYZ-001\n    type: requirement\n    text: No override at all.\n",
    )
    project = load_project(config_path=str(root / "refdes-project.yaml"))
    parse.load_items(project, require_ids=False)
    ids.validate_prefixes(project)
    message = next(d.message for d in project.warnings if "XYZ-001" in d.message)
    assert message == (
        "id 'XYZ-001' does not match this item's prefix 'REQ' "
        "(the 'requirement' type's default)"
    )


def test_prefix_mismatch_is_reported_not_silently_rewritten(tmp_path):
    """A mismatch is visible but never auto-fixed: the display id remains a
    human-facing convention even though surrogate keys carry identity."""
    root = _numeric_hint_project(
        tmp_path,
        "defaults:\n  type: requirement\n  prefix: CAN\n"
        "items:\n  - id: CNA-001\n    text: Typo in the prefix.\n",
    )
    before = (root / "items" / "r.yaml").read_text(encoding="utf-8")
    project = load_project(config_path=str(root / "refdes-project.yaml"))
    parse.load_items(project, require_ids=False)
    ids.validate_prefixes(project)
    assert (root / "items" / "r.yaml").read_text(encoding="utf-8") == before
    assert project.item_by_id("CNA-001").id == "CNA-001"  # not corrected in memory either


def test_prefix_with_a_free_form_category_segment_is_not_a_mismatch(tmp_path):
    """Part 2's category segment is typed straight into the id with no
    matching `prefix:` of its own (`IO-AI`, `EXP-PCIE`) -- this must not be
    confused with an actually-wrong prefix. Regression guard: split_id's own
    greedy match reads 'CON-IO' as one inseparable unit, which a naive
    equality check against the bare declared prefix would wrongly flag."""
    root = _numeric_hint_project(
        tmp_path,
        "items:\n  - id: REQ-IO-004\n    type: requirement\n    text: Category segment, no override.\n",
    )
    project = load_project(config_path=str(root / "refdes-project.yaml"))
    parse.load_items(project, require_ids=False)
    ids.validate_prefixes(project)
    assert not any("REQ-IO-004" in d.message for d in project.diagnostics)


def test_prefix_validation_skips_pending_items(tmp_path):
    root = _numeric_hint_project(
        tmp_path,
        "defaults:\n  type: requirement\n  prefix: CAN\n"
        "items:\n  - id:\n    text: Not allocated yet.\n",
    )
    project = load_project(config_path=str(root / "refdes-project.yaml"))
    parse.load_items(project, require_ids=False)
    ids.validate_prefixes(project)
    assert project.errors == []


def test_prefix_mismatch_is_a_nonblocking_warning_in_check_output(tmp_path, capsys):
    root = _numeric_hint_project(
        tmp_path,
        "defaults:\n  type: requirement\n  prefix: CAN\n"
        "items:\n  - id: CNA-001\n    text: Typo in the prefix.\n",
    )
    status = cli_mod.main(
        ["-c", str(root / "refdes-project.yaml"), "--no-write", "check"]
    )
    output = capsys.readouterr().out
    assert status == 0
    assert "WARNING items/r.yaml:" in output
    assert "id 'CNA-001' does not match this item's prefix 'CAN'" in output


# ------------------------------------------------- pure planning (Slice 3)

PLAN_SCHEMA = (
    "site: { title: T, out: _site }\n"
    "id: { width: 3 }\n"
    "types:\n"
    "  requirement: { prefix: REQ, fields: { text: { type: text, required: true } } }\n"
)


@pytest.fixture
def plan_project(tmp_path):
    write_project_config(tmp_path, PLAN_SCHEMA)
    items = tmp_path / "items"
    items.mkdir()
    (items / "r.yaml").write_text(
        "defaults: { type: requirement }\n"
        "items:\n"
        "  - id: REQ-001\n"
        "    text: One.\n",
        encoding="utf-8",
    )
    project = load_project(config_path=str(tmp_path / "refdes-project.yaml"))
    parse.load_items(project, require_ids=False)
    return tmp_path, project


def test_plan_new_id_previews_next_free_and_touches_nothing(plan_project):
    """The editor previews an id before the author saves; a preview must not
    reserve anything (docs/design/browser-editor.md, Slice 3)."""
    root, project = plan_project
    ledger = root / ".refdes" / "ids.yaml"
    before = (root / "items" / "r.yaml").read_bytes()

    new_id, reason = ids.plan_new_id(project, "requirement")
    assert reason is None and new_id == "REQ-002"
    # previewing twice is idempotent and writes no ledger, no item file
    again, _ = ids.plan_new_id(project, "requirement")
    assert again == "REQ-002"
    assert not ledger.exists()
    assert (root / "items" / "r.yaml").read_bytes() == before


def test_plan_new_id_explicit_override_is_honoured_or_refused(plan_project):
    _root, project = plan_project
    assert ids.plan_new_id(project, "requirement", explicit_id="REQ-042") == ("REQ-042", None)
    # a live id, a malformed id, and another type's prefix are all refused
    for bad in ("REQ-001", "not-an-id", "DEC-042"):
        new_id, reason = ids.plan_new_id(project, "requirement", explicit_id=bad)
        assert new_id is None and reason


def test_reserve_id_burns_so_the_next_plan_moves_on(plan_project):
    root, project = plan_project
    ledger = root / ".refdes" / "ids.yaml"
    ids.reserve_id(project, "REQ-002")
    assert ledger.exists()
    assert "REQ-002" in ledger.read_text(encoding="utf-8")
    new_id, _ = ids.plan_new_id(project, "requirement")
    assert new_id == "REQ-003"
