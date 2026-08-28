"""ids -- and: bare-numeric expand-and-freeze (finding 8 Part 1), prefix ("type segment") validation (finding 8 Parts 1/2).

Split out of the original monolithic tests/test_refdes.py.
"""

from __future__ import annotations

import os
import shutil
import textwrap

import pytest
import yaml
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
    shutil.copy(os.path.join(REPO, "refdes.yaml"), tmp_path / "refdes.yaml")
    items = tmp_path / "items" / "requirements"
    items.mkdir(parents=True)
    (items / "tmp.yaml").write_text(LIST_FILE, encoding="utf-8")
    return tmp_path


def test_allocation_never_renumbers_existing_items(temp_project):
    project = load_project(config_path=str(temp_project / "refdes.yaml"))
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
    project = load_project(config_path=str(temp_project / "refdes.yaml"))
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
    project2 = load_project(config_path=str(temp_project / "refdes.yaml"))
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
    (tmp_path / "refdes.yaml").write_text(
        "site: { title: T, out: _site }\n"
        "types:\n"
        "  requirement: { prefix: REQ, fields: { text: { type: text, required: true } } }\n",
        encoding="utf-8",
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

    project = load_project(config_path=str(tmp_path / "refdes.yaml"))
    parse.load_items(project, require_ids=False)
    assignments = ids.allocate(project)
    assert assignments and assignments[0][1] == "CAN-001"

    text = path.read_text(encoding="utf-8")
    assert text.count("id:") == 1, f"expected exactly one 'id:' key, got:\n{text}"
    assert "id: CAN-001" in text

    # Re-parse from disk, the way a second, separate `refdes id` invocation would --
    # this is what actually exposes the corruption: a duplicate key resolves to the
    # *last* one, so a still-broken file looks pending again here.
    project2 = load_project(config_path=str(tmp_path / "refdes.yaml"))
    parse.load_items(project2, require_ids=False)
    assert project2.items.get("CAN-001") is not None
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
    (tmp_path / "refdes.yaml").write_text(
        "site: { title: T, out: _site }\n"
        "types:\n"
        "  decision: { prefix: DEC, fields: { title: { type: text, required: true } }, body: {} }\n",
        encoding="utf-8",
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

    project = load_project(config_path=str(tmp_path / "refdes.yaml"))
    parse.load_items(project, require_ids=False)
    assignments = ids.allocate(project)
    assert assignments and assignments[0][1] == "DEC-001"

    text = path.read_text(encoding="utf-8")
    front_matter = text.split("---")[1]
    assert front_matter.count("id:") == 1, f"expected exactly one 'id:' key, got:\n{text}"
    assert "id: DEC-001" in front_matter

    project2 = load_project(config_path=str(tmp_path / "refdes.yaml"))
    parse.load_items(project2, require_ids=False)
    assert project2.items.get("DEC-001") is not None
    assert not project2.pending, "the item must not still look unallocated on reparse"

    assignments2 = ids.allocate(project2)
    assert assignments2 == []


def test_quoted_numeric_id_expands_in_place_no_duplicate_key(tmp_path):
    root = _numeric_hint_project(
        tmp_path,
        "defaults:\n  type: requirement\n  prefix: CAN\n"
        "items:\n  - id: \"042\"\n    text: Legacy number.\n",
    )
    project = load_project(config_path=str(root / "refdes.yaml"))
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
    (hand_root / "refdes.yaml").write_text(NUMERIC_HINT_SCHEMA, encoding="utf-8")
    hand_file = hand_root / "items" / "r.yaml"
    hand_file.write_text(
        "defaults:\n  type: requirement\n  prefix: CAN\n"
        "items:\n  - id: CAN-042\n    text: Same content either way.\n",
        encoding="utf-8",
    )

    exp_root = tmp_path / "expanded"
    (exp_root / "items").mkdir(parents=True)
    (exp_root / "refdes.yaml").write_text(NUMERIC_HINT_SCHEMA, encoding="utf-8")
    exp_file = exp_root / "items" / "r.yaml"
    exp_file.write_text(
        "defaults:\n  type: requirement\n  prefix: CAN\n"
        "items:\n  - id: \"042\"\n    text: Same content either way.\n",
        encoding="utf-8",
    )
    project = load_project(config_path=str(exp_root / "refdes.yaml"))
    parse.load_items(project, require_ids=False)
    ids.allocate(project)

    assert exp_file.read_text(encoding="utf-8") == hand_file.read_text(encoding="utf-8")


def test_quoted_numeric_id_expands_in_markdown_front_matter(tmp_path):
    (tmp_path / "refdes.yaml").write_text(
        "site: { title: T, out: _site }\n"
        "types:\n  decision: { prefix: DEC, fields: { title: { type: text, required: true } } }\n",
        encoding="utf-8",
    )
    (tmp_path / "items").mkdir()
    path = tmp_path / "items" / "d.md"
    path.write_text('---\nid: "5"\ntype: decision\ntitle: Md form.\n---\n', encoding="utf-8")

    project = load_project(config_path=str(tmp_path / "refdes.yaml"))
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
    project = load_project(config_path=str(root / "refdes.yaml"))
    parse.load_items(project, require_ids=False)
    ids.allocate(project)

    text = (root / "items" / "r.yaml").read_text(encoding="utf-8")
    reparsed = yaml.safe_load(text)
    assert reparsed["items"] == [{"id": "CAN-042", "text": "flow style entry"}]


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
    project = load_project(config_path=str(root / "refdes.yaml"))
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

    project = load_project(config_path=str(root / "refdes.yaml"))
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
    project = load_project(config_path=str(root / "refdes.yaml"))
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
    project = load_project(config_path=str(root / "refdes.yaml"))
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
    project = load_project(config_path=str(root / "refdes.yaml"))
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
    project = load_project(config_path=str(root / "refdes.yaml"))
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
    project = load_project(config_path=str(root / "refdes.yaml"))
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
    status = cli_mod.main(["-c", str(root / "refdes.yaml"), "id"])
    assert status == 1


def test_cli_id_succeeds_and_reports_zero_when_nothing_is_pending(tmp_path):
    root = _numeric_hint_project(
        tmp_path,
        "defaults:\n  type: requirement\n  prefix: CAN\n"
        "items:\n  - id: CAN-001\n    text: Already has an id.\n",
    )
    assert cli_mod.main(["-c", str(root / "refdes.yaml"), "id"]) == 0


# --------------------------------------- prefix ("type segment") validation (finding 8 Parts 1/2)


def test_prefix_mismatch_from_a_defaults_override_is_the_documented_error(tmp_path):
    root = _numeric_hint_project(
        tmp_path,
        "defaults:\n  type: requirement\n  prefix: CAN\n"
        "items:\n  - id: CNA-001\n    text: Typo in the prefix.\n",
    )
    project = load_project(config_path=str(root / "refdes.yaml"))
    parse.load_items(project, require_ids=False)
    ids.validate_prefixes(project)
    message = next(d.message for d in project.errors if "CNA-001" in d.message)
    assert message == "id 'CNA-001' does not match this item's prefix 'CAN' (from defaults:)"


def test_prefix_mismatch_against_the_types_own_default_names_the_type(tmp_path):
    root = _numeric_hint_project(
        tmp_path,
        "items:\n  - id: XYZ-001\n    type: requirement\n    text: No override at all.\n",
    )
    project = load_project(config_path=str(root / "refdes.yaml"))
    parse.load_items(project, require_ids=False)
    ids.validate_prefixes(project)
    message = next(d.message for d in project.errors if "XYZ-001" in d.message)
    assert message == (
        "id 'XYZ-001' does not match this item's prefix 'REQ' "
        "(the 'requirement' type's default)"
    )


def test_prefix_mismatch_is_reported_not_silently_rewritten(tmp_path):
    """A mismatch is Part 0's class of harm self-inflicted: auto-fixing an
    *existing* id would change the string every link is keyed on. The file
    must be untouched after a mismatch is reported."""
    root = _numeric_hint_project(
        tmp_path,
        "defaults:\n  type: requirement\n  prefix: CAN\n"
        "items:\n  - id: CNA-001\n    text: Typo in the prefix.\n",
    )
    before = (root / "items" / "r.yaml").read_text(encoding="utf-8")
    project = load_project(config_path=str(root / "refdes.yaml"))
    parse.load_items(project, require_ids=False)
    ids.validate_prefixes(project)
    assert (root / "items" / "r.yaml").read_text(encoding="utf-8") == before
    assert project.items["CNA-001"].id == "CNA-001"  # not corrected in memory either


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
    project = load_project(config_path=str(root / "refdes.yaml"))
    parse.load_items(project, require_ids=False)
    ids.validate_prefixes(project)
    assert not any("REQ-IO-004" in d.message for d in project.errors)


def test_prefix_validation_skips_pending_items(tmp_path):
    root = _numeric_hint_project(
        tmp_path,
        "defaults:\n  type: requirement\n  prefix: CAN\n"
        "items:\n  - id:\n    text: Not allocated yet.\n",
    )
    project = load_project(config_path=str(root / "refdes.yaml"))
    parse.load_items(project, require_ids=False)
    ids.validate_prefixes(project)
    assert project.errors == []


def test_prefix_validation_runs_as_part_of_a_real_build(tmp_path):
    root = _numeric_hint_project(
        tmp_path,
        "defaults:\n  type: requirement\n  prefix: CAN\n"
        "items:\n  - id: CNA-001\n    text: Typo in the prefix.\n",
    )
    project = load_project(config_path=str(root / "refdes.yaml"))
    parse.load_items(project, require_ids=False)
    build_mod.build(project, seal_write=False, reseal=False, accept_board_move=False)
    assert any(
        "does not match this item's prefix" in d.message for d in project.errors
    )
