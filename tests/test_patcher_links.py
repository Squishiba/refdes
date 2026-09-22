"""Link add/remove for the item-span patcher (docs/design/browser-editor.md,
"Slice 2 -- structured links").

Same posture as tests/test_patcher.py: the three source shapes a link list
takes today (scalar, flow list, block list) each get an add and a remove, the
byte-fidelity invariant is asserted on every plan, revert round-trips to the
original bytes, and every shape the patcher must not guess about is asserted
as a refusal -- a comment in the way, a duplicate, a target that is not there.
"""

from __future__ import annotations

import pytest
import yaml

from refdes.patcher import (
    AddLink,
    PatchPlan,
    Refusal,
    RemoveLink,
    apply_patch,
    plan_patch,
    revert_plan,
)


def refuse(text, ref, op, **kw):
    got = plan_patch(text, ref, op, **kw)
    assert isinstance(got, Refusal), f"expected a refusal, got {got!r}"
    return got


def plan(text, ref, op, **kw):
    got = plan_patch(text, ref, op, **kw)
    assert isinstance(got, PatchPlan), f"expected a plan, got {got!r}"
    return got


def edited(text, ref, op, **kw):
    """Plan, apply, and assert the one invariant every plan must satisfy."""
    got = plan(text, ref, op, **kw)
    new = apply_patch(text, got)
    assert new[: got.start] == text[: got.start]
    assert new[len(new) - len(text) + got.end :] == text[got.end :]
    return new, got


LINK_SCALAR = """\
# keep me
items:
  - id: DEC-001
    title: Chosen
    satisfies: REQ-001
  - id: DEC-002
    title: Other
    satisfies: [REQ-001, REQ-002]
  - id: DEC-003
    title: Blocky
    satisfies:
      - REQ-001
      - REQ-002
"""

NEW = "REQ-009@k7f3m2q9x4a"


def _targets(text, ref, verb="satisfies"):
    for entry in yaml.safe_load(text)["items"]:
        if entry["id"] == ref:
            value = entry.get(verb)
            if value is None:
                return None
            return value if isinstance(value, list) else [value]
    raise AssertionError(ref)


@pytest.mark.parametrize(
    "ref",
    ["DEC-001", "DEC-002", "DEC-003"],
    ids=["scalar", "flow-list", "block-list"],
)
def test_add_link_to_each_source_shape(ref):
    new, got = edited(LINK_SCALAR, ref, AddLink("satisfies", NEW))
    assert _targets(new, ref)[-1] == NEW
    assert got.op == "add_link" and got.field == "satisfies"
    assert apply_patch(new, revert_plan(got)) == LINK_SCALAR
    assert "# keep me" in new


def test_add_link_to_a_scalar_widens_it_and_keeps_the_original_spelling():
    text = "items:\n  - id: DEC-001\n    satisfies: 'REQ-001'\n"
    new, _ = edited(text, "DEC-001", AddLink("satisfies", NEW))
    assert new == f"items:\n  - id: DEC-001\n    satisfies: ['REQ-001', {NEW}]\n"


def test_add_link_to_a_flow_list_touches_only_the_insert():
    text = "items:\n  - id: D\n    satisfies: [A@k1, B@k2] # verb note\n"
    new, got = edited(text, "D", AddLink("satisfies", NEW))
    assert new == f"items:\n  - id: D\n    satisfies: [A@k1, B@k2, {NEW}] # verb note\n"
    assert got.replacement == f", {NEW}"


def test_add_link_to_a_block_list_appends_one_entry_at_the_local_indent():
    text = "items:\n  - id: D\n    satisfies:\n      - A@k1\n      - B@k2\n    status: ok\n"
    new, _ = edited(text, "D", AddLink("satisfies", NEW))
    assert new == (
        f"items:\n  - id: D\n    satisfies:\n      - A@k1\n      - B@k2\n      - {NEW}\n"
        "    status: ok\n"
    )


def test_add_link_after_a_block_entry_keeps_its_trailing_comment():
    text = "items:\n  - id: D\n    satisfies:\n      - A@k1 # why this\n"
    new, _ = edited(text, "D", AddLink("satisfies", NEW))
    assert new == f"items:\n  - id: D\n    satisfies:\n      - A@k1 # why this\n      - {NEW}\n"


def test_add_link_inserts_a_missing_verb_at_the_end_of_the_item():
    text = "items:\n  - id: D\n    title: T\n"
    new, got = edited(text, "D", AddLink("satisfies", NEW))
    # the insert path is the same one SetField uses for a missing field
    assert got.op == "insert" and got.field == "satisfies"
    assert new == f"items:\n  - id: D\n    title: T\n    satisfies: {NEW}\n"


def test_add_link_refuses_a_target_that_is_already_there():
    for ref in ("DEC-001", "DEC-002", "DEC-003"):
        got = refuse(LINK_SCALAR, ref, AddLink("satisfies", "REQ-001"))
        assert "already links" in got.reason


@pytest.mark.parametrize(
    "ref, wanted",
    [
        ("DEC-001", "REQ-001"),
        ("DEC-002", "REQ-001"),
        ("DEC-002", "REQ-002"),
        ("DEC-003", "REQ-001"),
        ("DEC-003", "REQ-002"),
    ],
)
def test_remove_link_from_each_source_shape(ref, wanted):
    new, got = edited(LINK_SCALAR, ref, RemoveLink("satisfies", wanted))
    remaining = _targets(new, ref)
    assert wanted not in (remaining or [])
    assert apply_patch(new, revert_plan(got)) == LINK_SCALAR


def test_remove_the_only_target_deletes_the_verb_entry():
    new, _ = edited(LINK_SCALAR, "DEC-001", RemoveLink("satisfies", "REQ-001"))
    assert "satisfies" not in new.split("DEC-002")[0]
    assert "# keep me" in new


def test_remove_from_a_flow_list_keeps_the_other_separators_exactly():
    text = "items:\n  - id: D\n    satisfies: [A@k1,B@k2, B@k3]\n"
    # the removed target takes the separator that followed it; the one that
    # preceded it stays exactly as the author spaced it
    new, _ = edited(text, "D", RemoveLink("satisfies", "k2"))
    assert new == "items:\n  - id: D\n    satisfies: [A@k1,B@k3]\n"
    new, _ = edited(text, "D", RemoveLink("satisfies", "k1"))
    assert new == "items:\n  - id: D\n    satisfies: [B@k2, B@k3]\n"


def test_remove_from_a_block_list_deletes_the_entry_line():
    text = "items:\n  - id: D\n    satisfies:\n      - A@k1\n      - B@k2\n    status: ok\n"
    new, _ = edited(text, "D", RemoveLink("satisfies", "k2"))
    assert new == "items:\n  - id: D\n    satisfies:\n      - A@k1\n    status: ok\n"


def test_remove_the_last_list_target_deletes_the_verb_entry_too():
    text = "items:\n  - id: D\n    title: T\n    satisfies:\n      - A@k1\n"
    new, _ = edited(text, "D", RemoveLink("satisfies", "A@k1"))
    assert new == "items:\n  - id: D\n    title: T\n"


def test_remove_matches_a_bare_spelling_by_the_composites_display_half():
    text = "items:\n  - id: D\n    satisfies: [REQ-001, REQ-002@kx]\n"
    new, _ = edited(text, "D", RemoveLink("satisfies", "REQ-001@zz"))
    assert new == "items:\n  - id: D\n    satisfies: [REQ-002@kx]\n"


def test_remove_matches_by_the_key_half_alone():
    text = "items:\n  - id: D\n    satisfies: [REQ-001@k1, REQ-002@k2]\n"
    new, _ = edited(text, "D", RemoveLink("satisfies", "k1"))
    assert new == "items:\n  - id: D\n    satisfies: [REQ-002@k2]\n"


def test_remove_refuses_a_target_that_is_not_linked():
    got = refuse(LINK_SCALAR, "DEC-002", RemoveLink("satisfies", "REQ-009"))
    assert "does not link" in got.reason
    got = refuse(LINK_SCALAR, "DEC-001", RemoveLink("refines", "REQ-001"))
    assert "no 'refines'" in got.reason


def test_remove_refuses_when_two_spellings_name_the_same_target():
    text = "items:\n  - id: D\n    satisfies: [REQ-001@k1, REQ-001@k1]\n"
    got = refuse(text, "D", RemoveLink("satisfies", "k1"))
    assert "2 times" in got.reason


def test_remove_refuses_when_a_comment_sits_on_the_line_being_deleted():
    text = "items:\n  - id: D\n    satisfies: REQ-001 # the reason\n"
    got = refuse(text, "D", RemoveLink("satisfies", "REQ-001"))
    assert "comment" in got.reason
    text = "items:\n  - id: D\n    satisfies:\n      - A@k1 # why\n      - B@k2\n"
    got = refuse(text, "D", RemoveLink("satisfies", "k1"))
    assert "comment" in got.reason


def test_remove_refuses_a_flow_separator_a_comment_owns():
    text = "items:\n  - id: D\n    satisfies: [A@k1, # first\n             B@k2]\n"
    got = refuse(text, "D", RemoveLink("satisfies", "k1"))
    assert "comma" in got.reason


def test_link_ops_on_markdown_front_matter():
    text = "---\nid: DEC-001\nsatisfies: [REQ-001]\n---\n\nProse.\n"
    new, got = edited(text, "DEC-001", AddLink("satisfies", NEW))
    assert got.shape == "md-front-matter"
    assert new.startswith(f"---\nid: DEC-001\nsatisfies: [REQ-001, {NEW}]\n---\n")
    assert apply_patch(new, revert_plan(got)) == text


def test_crlf_block_list_add_uses_the_files_break():
    text = "items:\r\n  - id: D\r\n    satisfies:\r\n      - A@k1\r\n"
    new, got = edited(text, "D", AddLink("satisfies", NEW))
    assert f"\r\n      - {NEW}\r\n" in new
    assert new.count("\n") == text.count("\n") + 1
    assert apply_patch(new, revert_plan(got)) == text


def test_add_link_refuses_a_mapping_valued_verb():
    text = "items:\n  - id: D\n    satisfies:\n      a: b\n"
    got = refuse(text, "D", AddLink("satisfies", NEW))
    assert isinstance(got, Refusal)


def test_add_link_refuses_protected_and_body_names():
    got = refuse(LINK_SCALAR, "DEC-001", AddLink("id", NEW))
    assert "not a link" in got.reason
